from flask import Flask, render_template, request, jsonify
import pandas as pd

app = Flask(__name__)

# =====================================================
# BI RATE
# =====================================================
LOADING = 0.25
BI_RATE = 0.0525

# =====================================================
# LOAD EXCEL TABLES
# =====================================================

def load_tables():
    data = {}
    excel_file = "tabel qx.xlsx"
    excel = pd.ExcelFile(excel_file)
    
    print("AVAILABLE SHEETS:")
    print(excel.sheet_names)
    
    mapping = {
        "male_mortality": excel.sheet_names[0],
        "female_mortality": excel.sheet_names[1],
        "male_critical": excel.sheet_names[2],
        "female_critical": excel.sheet_names[3]
    }
    
    for key, sheet in mapping.items():
        df = pd.read_excel(excel_file, sheet_name=sheet)
        df.columns = [str(c).strip() for c in df.columns]
        
        age_col = df.columns[0]
        value_col = df.columns[1]
        
        data[key] = pd.Series(
            df[value_col].values,
            index=df[age_col]
        ).to_dict()
        
    return data

db = load_tables()

# =====================================================
# CORE ENGINE
# =====================================================

def calculate_engine(usia_suami, usia_istri, benefit, premium_term, death_limit, ci_limit, interest=BI_RATE):
    v = 1 / (1 + interest)
    survival = 1.0
    pv_benefit = 0
    pv_premium = 0
    
    ledger = []
    survival_track = []

    # =================================================
    # MAIN PROJECTION
    # =================================================
    for t in range(111):
        age_s = usia_suami + t
        age_i = usia_istri + t

        # =============================================
        # MALE
        # =============================================
        if age_s > death_limit:
            qx_s_death = 0
        else:
            # HAPUS pembagian 1000 karena data Excel sudah desimal
            qx_s_death = db["male_mortality"].get(age_s, 0)

        if age_s > ci_limit:
            qx_s_ci = 0
        else:
            # TETAP bagi 1000 karena data tabel critical belum desimal
            qx_s_ci = (db["male_critical"].get(age_s, 0)) / 1000

        # =============================================
        # FEMALE
        # =============================================
        if age_i > death_limit:
            qx_i_death = 0
        else:
            # HAPUS pembagian 1000 karena data Excel sudah desimal
            qx_i_death = db["female_mortality"].get(age_i, 0)

        if age_i > ci_limit:
            qx_i_ci = 0
        else:
            # TETAP bagi 1000 karena data tabel critical belum desimal
            qx_i_ci = (db["female_critical"].get(age_i, 0)) / 1000

        # =============================================
        # DOUBLE DECREMENT
        # =============================================
        p_s = ((1 - qx_s_death) * (1 - qx_s_ci))
        p_i = ((1 - qx_i_death) * (1 - qx_i_ci))
        joint_survival = p_s * p_i
        q_joint = 1 - joint_survival

        # =============================================
        # PV BENEFIT
        # =============================================
        pv_benefit += (benefit * survival * q_joint * (v ** (t + 1)))

        # =============================================
        # PV PREMIUM
        # =============================================
        if t < premium_term:
            pv_premium += (survival * (v ** t))

        survival_track.append(survival)
        ledger.append({
            "year": t + 1,
            "husband_age": age_s,
            "wife_age": age_i,
            "survival_probability": round(survival, 6),
            "joint_decrement": round(q_joint, 6),
            "reserve": 0
        })
        
        survival *= joint_survival

    # =================================================
    # PREMIUM
    # =================================================
    net_premium = (pv_benefit / max(pv_premium, 1e-9))
    LOADING = 0.25
    gross_premium = (net_premium / (1 - LOADING))

    # =================================================
    # RESERVE (DISESUAIKAN PERSIS DENGAN EXCEL)
    # =================================================
    reserves = []
    pv_benefit_list = []
    pv_premium_list = []

    # 1. Buat list per baris seperti kolom di Excel
    for t in range(111):
        pv_ben = benefit * survival_track[t] * ledger[t]["joint_decrement"] * (v ** (t + 1))
        pv_benefit_list.append(pv_ben)
        
        if t < premium_term:
            pv_prem = survival_track[t] * (v ** t)
        else:
            pv_prem = 0
        pv_premium_list.append(pv_prem)

    # 2. Hitung SUM persis seperti ditarik di Excel
    for t in range(len(ledger)):
        sum_future_benefit = sum(pv_benefit_list[t:])
        sum_future_premium = sum(pv_premium_list[t:])
        
        # Sesuai data Excel Anda, nilainya menggunakan gross premium dan bisa negatif
        reserve = sum_future_benefit - (gross_premium * sum_future_premium)
        reserves.append(round(reserve, 2))

    # =================================================
    # UPDATE LEDGER
    # =================================================
    for i in range(len(ledger)):
        ledger[i]["reserve"] = reserves[i]

    # =================================================
    # RETURN
    # =================================================
    return {
        "premium": round(gross_premium, 2),
        "monthly_premium": round(gross_premium / 12, 2),
        "pv_benefit": round(pv_benefit, 2),
        "pv_premium": round(pv_premium, 2),
        "ledger": ledger
    }

# =====================================================
# PACKAGE 85
# =====================================================
def calculate_package_85(usia_suami, usia_istri, benefit, premium_term):
    return calculate_engine(
        usia_suami, usia_istri, benefit, premium_term,
        death_limit=85, ci_limit=85
    )

# =====================================================
# PACKAGE 111
# =====================================================
def calculate_package_111(usia_suami, usia_istri, benefit, premium_term):
    return calculate_engine(
        usia_suami, usia_istri, benefit, premium_term,
        death_limit=111, ci_limit=85
    )

# =====================================================
# ROUTES
# =====================================================
@app.route("/")
def customer():
    return render_template("customer.html", bi_rate=round(BI_RATE * 100, 2))

@app.route("/actuary")
def actuary():
    return render_template("actuary.html", bi_rate=round(BI_RATE * 100, 2))

# =====================================================
# CUSTOMER API
# =====================================================
@app.route("/calculate_customer", methods=["POST"])
def calculate_customer():
    data = request.json
    usia_suami = int(data["usia_suami"])
    usia_istri = int(data["usia_istri"])
    benefit = float(data["benefit"])
    premium_term = int(data["term"])
    
    result_85 = calculate_package_85(usia_suami, usia_istri, benefit, premium_term)
    result_111 = calculate_package_111(usia_suami, usia_istri, benefit, premium_term)
    
    return jsonify({
        "premium_85": result_85["premium"],
        "premium_111": result_111["premium"],
        "monthly_85": result_85["monthly_premium"],
        "monthly_111": result_111["monthly_premium"]
    })

# =====================================================
# ACTUARY API
# =====================================================
@app.route("/calculate_actuary", methods=["POST"])
def calculate_actuary():
    data = request.json
    usia_suami = int(data["usia_suami"])
    usia_istri = int(data["usia_istri"])
    benefit = float(data["benefit"])
    premium_term = int(data["term"])
    
    result_85 = calculate_package_85(usia_suami, usia_istri, benefit, premium_term)
    result_111 = calculate_package_111(usia_suami, usia_istri, benefit, premium_term)
    
    return jsonify({
        "package85": result_85,
        "package111": result_111
    })

# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    app.run(debug=True)
import time
import requests
import json
import os
import sys
import threading
import math
import collections
import numpy as np
import optuna
from scipy import stats as scipy_stats
from pymongo import MongoClient
from flask import Flask

optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️  CONFIG
# ==========================================
API_ENDPOINT  = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"
MONGO_URI     = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"

USER_AUTH_DATA = {
    "accessToken":  "d93b0a3da4204530bbf97944c5353348",
    "refreshToken": "a48b8445b47545e8bf55b5ebcdd303c5.fd44c0a6c99b455c84c845298d835679",
    "wsToken":      "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJnZW5kZXIiOjAsImNhblZpZXdTdGF0IjpmYWxzZSwiZGlzcGxheU5hbWUiOiJzb25ndmVkZW0yMCIsImJvdCI6MCwiaXNNZXJjaGFudCI6ZmFsc2UsInZlcmlmaWVkQmFua0FjY291bnQiOnRydWUsInBsYXlFdmVudExvYmJ5IjpmYWxzZSwiY3VzdG9tZXJJZCI6MjM5OTUzMjE1LCJhZmZJZCI6ImRlZmF1bHQiLCJiYW5uZWQiOmZhbHNlLCJicmFuZCI6InN1bi53aW4iLCJlbWFpbCI6IiIsInRpbWVzdGFtcCI6MTc3ODA0MzQyMjAxNiwibG9ja0dhbWVzIjpbXSwiYW1vdW50IjowLCJsb2NrQ2hhdCI6ZmFsc2UsInBob25lVmVyaWZpZWQiOnRydWUsImlwQWRkcmVzcyI6IjExMy4xNzUuMTAwLjU3IiwibXV0ZSI6ZmFsc2UsImF2YXRhciI6Imh0dHBzOi8vaW1hZ2VzLnN3aW5zaG9wLm5ldC9pbWFnZXMvYXZhdGFyL2F2YXRhcl8xMC5wbmciLCJwbGF0Zm9ybUlkIjoyLCJ1c2VySWQiOiIwMDM3NDA2OC04YmZiLTQ5NTYtOWIxMi0yODkzYzMxMDcxNjAiLCJlbWFpbFZlcmlmaWVkIjpudWxsLCJyZWdUaW1lIjoxNzQ1NTkyNjU1ODA3LCJwaG9uZSI6Ijg0MzI5Njg5OTcxIiwiZGVwb3NpdCI6dHJ1ZSwidXNlcm5hbWUiOiJTQ19zb25ndmVkZW0xMCJ9.4jl_XtPCRLFuSOrBlfAtaSz3kg27oIqZFqcHwPv34G0",
    "signature":    "366DB52754A4C6B5AE4D3169940BE3BB2C046D859898F0B7E6BDFA3F84069E77B309CE8EE69EA0482776D271C521EDC2D223503CA0B182D6F8DB9E4C0E49C9514DF7418F284DF0AD4F603F23018D0914A225350B66C82C2A17FC2297CF27BF13D4DDE48E06427520B0A99BB8EC0EA3A6947FD1D255BE3AB92C66F0DD475EF5F9",
    "userId":       "00374068-8bfb-4956-9b12-2893c3107160",
    "username":     "SC_songvedem10"
}

HEADERS = {
    "Authorization": f"Bearer {USER_AUTH_DATA['accessToken']}",
    "wsToken":       USER_AUTH_DATA['wsToken'],
    "signature":     USER_AUTH_DATA['signature'],
    "Content-Type":  "application/json"
}

HISTORY_MAX  = 500
REQUIRED_LEN = 20

# ==========================================
# 🛠️  MONGODB
# ==========================================
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    db           = mongo_client['sunwin_database']
    collection   = db['history']
    mongo_client.admin.command('ping')
    print("✅ KẾT NỐI MONGODB THÀNH CÔNG!")
except Exception as e:
    print(f"❌ LỖI KẾT NỐI MONGODB: {e}")
    mongo_client = None
    collection   = None

app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "🔥 SUNWIN AI v8 — ADAPTIVE ENSEMBLE + META-LEARNING ACTIVE"

@app.route('/health')
def health():
    return json.dumps({"status": "ok", "time": time.time()})


# ==========================================
# 🔢  TOÁN HỌC CORE
# ==========================================
def _sigmoid(x: float) -> float:
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))

def _to_log_odds(p: float) -> float:
    p = max(1e-7, min(1.0 - 1e-7, p))
    return math.log(p / (1.0 - p))

def shannon_entropy(seq: list, window: int = 40) -> float:
    s = seq[-window:] if len(seq) >= window else seq
    if not s:
        return 1.0
    t = sum(1 for c in s if c == 'T')
    n = len(s)
    if t == 0 or t == n:
        return 0.0
    p = t / n
    return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)

def runs_test_pvalue(seq: list) -> float:
    if len(seq) < 10:
        return 1.0
    arr = np.array([1 if x == 'T' else 0 for x in seq[-100:]])
    n1  = int(arr.sum())
    n2  = len(arr) - n1
    if n1 == 0 or n2 == 0:
        return 0.0
    runs = 1 + sum(1 for i in range(1, len(arr)) if arr[i] != arr[i - 1])
    mu   = 1 + 2 * n1 * n2 / (n1 + n2)
    var  = (2 * n1 * n2 * (2 * n1 * n2 - n1 - n2)) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    if var <= 0:
        return 1.0
    z    = (runs - mu) / math.sqrt(var)
    pval = 2 * (1 - scipy_stats.norm.cdf(abs(z)))
    return float(pval)

def autocorrelation_lag1(seq: list, window: int = 60) -> float:
    s   = [1 if c == 'T' else 0 for c in seq[-window:]]
    if len(s) < 5:
        return 0.0
    a   = np.array(s[:-1], dtype=float)
    b   = np.array(s[1:],  dtype=float)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ==========================================
# 🧠 ENGINE 1: MARKOV ĐA BẬC + BIC MODEL SELECTION
# ==========================================
def engine_markov_bic(seq: list, max_order: int = 6) -> tuple:
    if len(seq) < 5:
        return 0.5, 0.0

    search = seq[-200:]
    best_order   = 1
    best_bic     = float('inf')
    best_p_tai   = 0.5

    for order in range(1, min(max_order + 1, len(search) // 5 + 1)):
        ctx   = tuple(search[-order:])
        t_cnt, x_cnt = 0, 0
        for i in range(len(search) - order):
            if tuple(search[i:i + order]) == ctx:
                if search[i + order] == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total < 3:
            continue

        p_t  = (t_cnt + 1) / (total + 2)
        ll   = t_cnt * math.log(p_t + 1e-9) + x_cnt * math.log(1 - p_t + 1e-9)
        k    = 2 ** order 
        bic  = -2 * ll + k * math.log(total + 1)

        if bic < best_bic:
            best_bic   = bic
            best_order = order
            best_p_tai = p_t

    ctx   = tuple(search[-best_order:])
    t_cnt, x_cnt = 0, 0
    for i in range(len(search) - best_order):
        if tuple(search[i:i + best_order]) == ctx:
            if search[i + best_order] == 'T':
                t_cnt += 1
            else:
                x_cnt += 1
    total  = t_cnt + x_cnt
    conf   = min(1.0, total / 12.0) * abs(best_p_tai - 0.5) * 2.0

    return best_p_tai, conf


# ==========================================
# 🧠 ENGINE 2: N-GRAM + CHI-SQUARE SIGNIFICANCE TEST
# ==========================================
def engine_ngram_significant(seq: list) -> tuple:
    if len(seq) < 5:
        return 0.5, 0.0

    search = seq[-200:]

    for n in (7, 6, 5, 4, 3):
        if len(search) <= n + 2:
            continue
        pattern = tuple(search[-n:])
        t_cnt, x_cnt = 0, 0
        all_t, all_x = 0, 0

        for i in range(len(search) - n):
            nxt = search[i + n]
            if nxt == 'T':
                all_t += 1
            else:
                all_x += 1
            if tuple(search[i:i + n]) == pattern:
                if nxt == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total < 4:
            continue

        total_all = all_t + all_x
        if total_all == 0:
            continue

        expected_t = total * (all_t / total_all)
        expected_x = total * (all_x / total_all)
        if expected_t < 1 or expected_x < 1:
            continue

        chi2 = ((t_cnt - expected_t) ** 2 / expected_t +
                (x_cnt - expected_x) ** 2 / expected_x)
        pval = float(1 - scipy_stats.chi2.cdf(chi2, df=1))

        if pval < 0.20:
            p_t  = (t_cnt + 1) / (total + 2)
            conf = min(1.0, (0.20 - pval) / 0.20) * min(1.0, total / 8.0)
            return p_t, conf

    return 0.5, 0.0


# ==========================================
# 🧠 ENGINE 3: STREAK ANALYSIS NÂNG CẤP (Hazard Rate)
# ==========================================
def engine_streak_hazard(seq: list) -> tuple:
    if len(seq) < 5:
        return 0.5, 0.0

    last      = seq[-1]
    streak    = 0
    for c in reversed(seq):
        if c == last:
            streak += 1
        else:
            break

    if streak < 1:
        return 0.5, 0.0

    hazard    = {}  
    search    = seq[:-streak] if streak < len(seq) else seq

    i = 0
    while i < len(search):
        run_val = search[i]
        run_len = 0
        j       = i
        while j < len(search) and search[j] == run_val:
            run_len += 1
            j       += 1
        for step in range(1, run_len + 1):
            k = step
            if j < len(search):
                rev = (search[j] != run_val)
                if k not in hazard:
                    hazard[k] = [0, 0]
                if rev:
                    hazard[k][0] += 1
                else:
                    hazard[k][1] += 1
        i = j

    k    = min(streak, 8)
    rev_count, cont_count = 0, 0
    for step in range(max(1, k - 1), k + 2):
        if step in hazard:
            rev_count  += hazard[step][0]
            cont_count += hazard[step][1]

    total = rev_count + cont_count
    if total < 3:
        p_rev = min(0.5 + streak * 0.04, 0.72)
        conf  = 0.2
    else:
        p_rev = (rev_count + 1) / (total + 2)
        conf  = min(1.0, total / 10.0) * abs(p_rev - 0.5) * 2.0

    p_tai = (1.0 - p_rev) if last == 'T' else p_rev
    return p_tai, conf


# ==========================================
# 🧠 ENGINE 4: WEIGHTED EMA + MOMENTUM
# ==========================================
def engine_ema_momentum(seq: list) -> tuple:
    if len(seq) < 5:
        return 0.5, 0.0

    window = seq[-80:]
    vals   = [1.0 if c == 'T' else 0.0 for c in window]

    ema_s = 0.5
    for v in vals:
        ema_s = 0.35 * v + 0.65 * ema_s

    ema_l = 0.5
    for v in vals:
        ema_l = 0.12 * v + 0.88 * ema_l

    momentum = ema_s - ema_l   
    p_tai = _sigmoid(momentum * 6.0)   
    conf  = min(1.0, abs(momentum) * 4.0)

    return p_tai, conf


# ==========================================
# 🧠 ENGINE 5: TONG DISTRIBUTION ANALYSIS
# ==========================================
def engine_tong_distribution(tong_list: list) -> tuple:
    if len(tong_list) < 10:
        return 0.5, 0.0

    recent  = tong_list[-40:]
    MEAN_T  = 10.5
    STD_T   = 2.415  

    m       = sum(recent) / len(recent)
    z       = (m - MEAN_T) / (STD_T / math.sqrt(len(recent)))

    p_tai   = _sigmoid(-z * 0.5)
    conf    = min(1.0, abs(z) / 2.0)

    extremes = sum(1 for t in recent[-10:] if t <= 6 or t >= 15)
    if extremes >= 4:
        p_tai = 0.5 + (p_tai - 0.5) * 0.3   
        conf  *= 0.5

    return p_tai, conf


# ==========================================
# 🧠 ENGINE 6: FOURIER PERIODICITY DETECTOR
# ==========================================
def engine_fourier_period(seq: list) -> tuple:
    if len(seq) < 20:
        return 0.5, 0.0

    window = seq[-128:]
    arr    = np.array([1.0 if c == 'T' else -1.0 for c in window])

    fft_vals = np.abs(np.fft.rfft(arr))
    freqs    = np.fft.rfftfreq(len(arr))

    fft_vals[0] = 0
    if len(fft_vals) < 2:
        return 0.5, 0.0

    dom_idx   = int(np.argmax(fft_vals[1:])) + 1
    dom_power = fft_vals[dom_idx]
    total_pow = fft_vals.sum()

    if total_pow == 0:
        return 0.5, 0.0

    rel_power = dom_power / total_pow   

    if rel_power < 0.12:
        return 0.5, 0.0

    period    = 1.0 / (freqs[dom_idx] + 1e-9)
    pos_in_cycle = len(window) % max(1, round(period))
    phase_ratio  = pos_in_cycle / max(1, round(period))

    if arr[-1] > 0:  
        p_tai = 0.5 - 0.15 * rel_power * math.cos(2 * math.pi * phase_ratio)
    else:
        p_tai = 0.5 + 0.15 * rel_power * math.cos(2 * math.pi * phase_ratio)

    p_tai = max(0.2, min(0.8, p_tai))
    conf  = min(1.0, rel_power * 3.0) * 0.6   

    return p_tai, conf


# ==========================================
# 🧠 ENGINE 7: REGIME DETECTOR (HOT / COLD / CHOP)
# ==========================================
def engine_regime(seq: list) -> tuple:
    if len(seq) < 10:
        return 0.5, 0.0

    def freq_t(window):
        s = seq[-window:] if len(seq) >= window else seq
        return sum(1 for c in s if c == 'T') / len(s)

    def chop_rate(window):
        s = seq[-window:] if len(seq) >= window else seq
        return sum(1 for i in range(1, len(s)) if s[i] != s[i-1]) / max(1, len(s) - 1)

    f5, f15, f30  = freq_t(5), freq_t(15), freq_t(30)
    c5, c15       = chop_rate(5), chop_rate(15)

    if c5 > 0.70 and c15 > 0.65:
        last  = seq[-1]
        p_tai = 0.30 if last == 'T' else 0.70
        conf  = min(1.0, (c5 - 0.70) * 5.0 + (c15 - 0.65) * 3.0)
        return p_tai, conf

    if f5 > 0.70 and f15 > 0.60 and f30 > 0.55:
        p_tai = 0.65
        conf  = min(1.0, (f5 - 0.5) * 1.5)
        return p_tai, conf

    if f5 < 0.30 and f15 < 0.40 and f30 < 0.45:
        p_tai = 0.35
        conf  = min(1.0, (0.5 - f5) * 1.5)
        return p_tai, conf

    return (f30 * 0.4 + f15 * 0.35 + f5 * 0.25), 0.15


# ==========================================
# 🧠 ENGINE 8: META-LEARNER (Accuracy Tracker Per Engine)
# ==========================================
class MetaLearner:
    def __init__(self, n_engines: int = 8, window: int = 30):
        self.n         = n_engines
        self.window    = window
        self.histories = [collections.deque(maxlen=window) for _ in range(n_engines)]

    def update(self, engine_preds: list, actual: str):
        for i, p in enumerate(engine_preds):
            pred_label = 'T' if p >= 0.5 else 'X'
            correct    = 1 if pred_label == actual else 0
            self.histories[i].append(correct)

    def get_accuracy_weights(self) -> list:
        weights = []
        for hist in self.histories:
            if len(hist) < 5:
                weights.append(1.0)
            else:
                acc = sum(hist) / len(hist)
                w = 0.5 + acc * 1.2
                weights.append(round(w, 3))
        return weights


# ==========================================
# 🧠 CORE: ADAPTIVE BAYESIAN ENSEMBLE
# ==========================================
def adaptive_bayesian_combine(
    engine_results: list,   
    base_weights: list,
    meta_weights: list,
    entropy: float,
    runs_pval: float,
    autocorr: float
) -> tuple:
    if entropy > 0.92:
        entropy_scale = 0.25
    elif entropy > 0.80:
        entropy_scale = 0.50
    elif entropy > 0.65:
        entropy_scale = 0.75
    else:
        entropy_scale = 1.0

    runs_scale = 1.0 - max(0.0, runs_pval - 0.20) * 0.8
    combined_scale = entropy_scale * runs_scale

    log_odds_sum  = 0.0
    weight_sum    = 0.0
    conf_weighted = 0.0

    for i, (p_tai, conf) in enumerate(engine_results):
        bw    = base_weights[i]
        mw    = meta_weights[i]
        eff_w = bw * mw * max(0.3, conf + 0.4)

        lo    = _to_log_odds(p_tai)
        log_odds_sum  += eff_w * combined_scale * lo
        weight_sum    += eff_w
        conf_weighted += eff_w * conf

    if weight_sum == 0:
        return 0.5, 0.0

    if abs(autocorr) > 0.08:
        autocorr_lo   = autocorr * 0.4  
        log_odds_sum += autocorr_lo * combined_scale

    p_tai_final  = _sigmoid(log_odds_sum)
    avg_conf     = conf_weighted / weight_sum * combined_scale
    avg_conf     = max(0.0, min(1.0, avg_conf))

    return p_tai_final, avg_conf


# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH v8
# ==========================================
class SunwinLogic_v8:
    def __init__(self):
        self.last_session_id      = None
        self.total_played         = 0
        self.total_won            = 0
        self.last_final_pred      = None
        self.predicted_session_id = None
        self.history_predictions  = {}
        self.tune_counter         = 0

        # --- BASE WEIGHTS 8 ENGINE ---
        self.weights = [
            2.0,   # E1: Markov BIC
            4.0,   # E2: N-gram chi-square (Boost patterns)
            1.8,   # E3: Streak hazard
            1.2,   # E4: EMA momentum
            0.5,   # E5: Tong distribution
            0.7,   # E6: Fourier period
            1.5,   # E7: Regime detector
            0.0,   # E8: placeholder 
        ]

        # --- META-LEARNER ---
        self.meta = MetaLearner(n_engines=7, window=30)

        # --- BAIT MATRIX ---
        self.last_engine_preds   = None
        self.last_final_pred     = None
        self.last_raw_pred       = None
        self.last_raw_key        = None
        self.last_raw_bucket     = None

        self.bait_matrix = {
            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False},
            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False}
        }
        self.bucket_streaks = {
            k: {b: {'loss': 0, 'win': 0} for b in [50, 60, 70, 80, 90, 100]}
            for k in self.bait_matrix
        }

        # --- WATCHDOG ---
        self.last_data_time    = time.time()
        self.api_fail_count    = 0
        self._watchdog_started = False
        self._start_watchdog()

    # ==========================================
    # 🐕 WATCHDOG
    # ==========================================
    def _start_watchdog(self):
        if self._watchdog_started:
            return
        self._watchdog_started = True

        def _watch():
            while True:
                try:
                    time.sleep(60)
                    elapsed = time.time() - self.last_data_time
                    mins    = int(elapsed / 60)
                    if elapsed > 600:
                        print(f"\n🚨 [WATCHDOG] {mins} PHÚT KHÔNG CÓ DỮ LIỆU — Reset session!")
                        self.last_session_id = None
                        self.last_data_time  = time.time()
                    elif elapsed > 300:
                        print(f"⚠️ [WATCHDOG] {mins} phút chưa có phiên mới.")
                except Exception as e:
                    print(f"⚠️ [WATCHDOG] Lỗi: {e}")

        t      = threading.Thread(target=_watch, daemon=True)
        t.name = "WatchdogThread"
        t.start()

    # ==========================================
    # 💾 MONGODB
    # ==========================================
    def load_data(self) -> list:
        if collection is None:
            return []
        try:
            doc = collection.find_one({'config': 'history_array'})
            return doc['data'] if doc and 'data' in doc else []
        except Exception as e:
            print(f"❌ [DB] Lỗi đọc: {e}")
            return []

    def save_data(self, data: list):
        if collection is None:
            return
        try:
            collection.update_one(
                {'config': 'history_array'},
                {'$set': {'data': data[-HISTORY_MAX:]}},
                upsert=True
            )
        except Exception as e:
            print(f"❌ [DB] Lỗi lưu: {e}")

    # ==========================================
    # 📊 DASHBOARD SYNC
    # ==========================================
    def get_confidence_bucket(self, percent: float) -> int:
        if percent >= 100: return 100
        elif percent >= 90: return 90
        elif percent >= 80: return 80
        elif percent >= 70: return 70
        elif percent >= 60: return 60
        else:               return 50

    def sync_to_dashboard(self, next_phien: int, pred: str, detail: str):
        try:
            wr        = (self.total_won / self.total_played * 100) if self.total_played > 0 else 0
            full_data = self.load_data()
            hist      = []
            for item in full_data[-20:]:
                phien      = item['phien']
                actual_res = "TÀI" if item['tong'] > 10 else "XỈU"
                bot_pred   = self.history_predictions.get(str(phien), "--")
                hist.append({
                    "phien":  phien,
                    "pred":   bot_pred,
                    "actual": actual_res,
                    "win":    (bot_pred == actual_res) if bot_pred != "--" else None
                })
            payload = {
                "result":       pred,
                "detail":       detail,
                "win_rate":     round(wr, 1),
                "total_played": self.total_played,
                "history":      hist[::-1]
            }
            requests.post(SYNC_ENDPOINT, json=payload, headers=HEADERS, timeout=8)
        except Exception as e:
            print(f"⚠️ [SYNC] Dashboard lỗi: {e}")

    # ==========================================
    # ⚙️ OPTUNA — Tối ưu 7 base weights
    # ==========================================
    def run_optuna_tuning(self, data: list):
        if len(data) < 35:
            return
        print("\n🔄 [OPTUNA] Tối ưu 7 base weights trên lịch sử thực...")

        def objective(trial):
            ws = [
                trial.suggest_float('w0', 0.5, 6.0),   
                trial.suggest_float('w1', 0.5, 5.0),   
                trial.suggest_float('w2', 0.2, 4.0),   
                trial.suggest_float('w3', 0.1, 3.0),   
                trial.suggest_float('w4', 0.0, 1.5),   
                trial.suggest_float('w5', 0.0, 2.0),   
                trial.suggest_float('w6', 0.2, 3.5),   
            ]

            test_len = min(35, len(data) - REQUIRED_LEN)
            correct  = 0

            for i in range(len(data) - test_len, len(data)):
                past = data[:i]
                if len(past) < REQUIRED_LEN:
                    continue

                seq       = ["T" if x['tong'] > 10 else "X" for x in past[-200:]]
                tong_list = [x['tong'] for x in past[-60:]]
                entropy   = shannon_entropy(seq)
                runs_pval = runs_test_pvalue(seq)
                autocorr  = autocorrelation_lag1(seq)

                results = [
                    engine_markov_bic(seq),
                    engine_ngram_significant(seq),
                    engine_streak_hazard(seq),
                    engine_ema_momentum(seq),
                    engine_tong_distribution(tong_list),
                    engine_fourier_period(seq),
                    engine_regime(seq),
                ]
                meta_ws  = [1.0] * 7
                p_tai, _ = adaptive_bayesian_combine(
                    results, ws, meta_ws, entropy, runs_pval, autocorr
                )
                pred   = "TÀI" if p_tai >= 0.5 else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1

            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=80)

        best        = study.best_params
        self.weights = [round(best[f'w{i}'], 3) for i in range(7)]
        names        = ["Markov", "Ngram", "Streak", "EMA", "Tong", "Fourier", "Regime"]
        w_str        = " | ".join(f"{n}={w}" for n, w in zip(names, self.weights))
        print(f"✅ [OPTUNA] Xong! {w_str}\n")

    # ==========================================
    # 🧮 PHÂN TÍCH & DỰ ĐOÁN
    # ==========================================
    def analyze_next_round(self, next_session_id: int):
        data = self.load_data()

        print(f"\n{'='*100}")
        print(f"🎯 PHÂN TÍCH PHIÊN {next_session_id}")
        print(f"{'='*100}")

        if len(data) < REQUIRED_LEN:
            msg = f"Thu thập dữ liệu: {len(data)}/{REQUIRED_LEN} ván..."
            print(f"⚠️ {msg}")
            self.sync_to_dashboard(next_session_id, "WAIT", msg)
            return

        seq       = ["T" if x['tong'] > 10 else "X" for x in data[-200:]]
        tong_list = [x['tong'] for x in data[-80:]]

        # ─── PHÂN TÍCH THỐNG KÊ ───
        entropy   = shannon_entropy(seq, window=40)
        runs_pval = runs_test_pvalue(seq)
        autocorr  = autocorrelation_lag1(seq)

        if entropy > 0.92:
            ent_label = "🔴 CAO — ngẫu nhiên mạnh"
        elif entropy > 0.75:
            ent_label = "🟡 TRUNG BÌNH"
        else:
            ent_label = "🟢 THẤP — pattern rõ"

        if runs_pval < 0.05:
            runs_label = "🟢 Có cấu trúc (p<0.05)"
        elif runs_pval < 0.15:
            runs_label = "🟡 Có thể có pattern"
        else:
            runs_label = "🔴 Ngẫu nhiên cao"

        ac_label = f"{'dương (+tiếp diễn)' if autocorr > 0.05 else 'âm (+xen kẽ)' if autocorr < -0.05 else 'trung tính'}"

        # ─── CHẠY 7 ENGINE ───
        r1 = engine_markov_bic(seq)
        r2 = engine_ngram_significant(seq)
        r3 = engine_streak_hazard(seq)
        r4 = engine_ema_momentum(seq)
        r5 = engine_tong_distribution(tong_list)
        r6 = engine_fourier_period(seq)
        r7 = engine_regime(seq)

        engine_results = [r1, r2, r3, r4, r5, r6, r7]

        # ─── META-LEARNING WEIGHTS ───
        meta_ws = self.meta.get_accuracy_weights()
        w7      = self.weights[:7]

        # ─── TỔNG HỢP ADAPTIVE BAYESIAN ───
        p_tai_raw, overall_conf = adaptive_bayesian_combine(
            engine_results, w7, meta_ws,
            entropy, runs_pval, autocorr
        )
        
        # Đảo ngược kết quả logic tự động 
        p_tai = 1.0 - p_tai_raw
        p_xiu = 1.0 - p_tai

        # ─── CHỐT GỐC ───
        chot_goc     = "TÀI" if p_tai >= 0.5 else "XỈU"
        conf_percent = round(max(p_tai, p_xiu) * 100.0, 1)
        matrix_key   = chot_goc
        bucket       = self.get_confidence_bucket(conf_percent)
        current_wr   = (self.total_won / self.total_played * 100) if self.total_played > 0 else 50.0

        # ─── LOG ───
        E_NAMES = [
            "Markov BIC (bậc tối ưu)  ",
            "N-gram + Chi-square      ",
            "Streak Hazard Rate       ",
            "EMA Momentum (S/L cross) ",
            "Tong Z-score MeanRev     ",
            "Fourier Periodicity      ",
            "Regime Detector (H/C/Ch) ",
        ]

        print(f"")
        print(f"📊 PHÂN TÍCH THỐNG KÊ:")
        print(f"   Entropy (40v)  : {entropy:.4f}  → {ent_label}")
        print(f"   Runs test      : p={runs_pval:.3f}  → {runs_label}")
        print(f"   Autocorr lag-1 : r={autocorr:+.3f}  → {ac_label}")
        combined_s = max(0.25, (1.0 - entropy * 0.7)) * (1.0 - max(0.0, runs_pval - 0.20) * 0.8)
        print(f"   Signal scale   : {combined_s:.3f}")
        print(f"")
        print(f"📘 7 ENGINE — P(TÀI) | Conf | MetaW | BaseW")
        for i, ((p, c), name) in enumerate(zip(engine_results, E_NAMES)):
            mw = meta_ws[i] if i < len(meta_ws) else 1.0
            bw = w7[i]      if i < len(w7)      else 1.0
            bar_t = "█" * int(p * 20)
            bar_x = "░" * (20 - int(p * 20))
            print(f"   E{i+1} {name}: {p*100:5.1f}% [{bar_t}{bar_x}] "
                  f"conf={c:.2f} meta={mw:.2f} base={bw}")
        print(f"")
        print(f"   ─── ADAPTIVE BAYESIAN ENSEMBLE ───")
        print(f"   => P(TÀI) = {p_tai*100:.2f}%  |  P(XỈU) = {p_xiu*100:.2f}%")
        print(f"   => Overall confidence = {overall_conf:.3f}")
        print(f"   => CHỐT GỐC : {chot_goc} ({conf_percent}%)  [Bucket {bucket}%]")

        # ─── BAIT MATRIX ───
        nguong    = 4 
        note      = ""
        chot_cuoi = chot_goc

        if self.bait_matrix[matrix_key][bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note      = f"⚠️ {matrix_key} {bucket}% đang lừa → ÉP BẺ → {chot_cuoi}"
        else:
            note = "✅ Vào theo Adaptive Bayesian"

        # ─── LƯU TRẠNG THÁI ───
        self.last_engine_preds    = [p for p, _ in engine_results]
        self.last_raw_pred        = chot_goc
        self.last_raw_key         = matrix_key
        self.last_raw_bucket      = bucket
        self.last_final_pred      = chot_cuoi
        self.history_predictions[str(next_session_id)] = chot_cuoi
        self.predicted_session_id = next_session_id

        wr_str = f" [WR: {self.total_won}/{self.total_played} = {current_wr:.1f}%]" if self.total_played > 0 else ""
        print(f"{'─'*100}")
        print(f"🔥 LỆNH CHỐT CUỐI : VÀO {chot_cuoi}  ← {note}{wr_str}")

        detail = (
            f"Adaptive-Bayes {chot_goc}({conf_percent:.1f}%) "
            f"H={entropy:.2f} runs_p={runs_pval:.2f} → {note}"
        )
        self.sync_to_dashboard(next_session_id, chot_cuoi, detail)
        print(f"{'='*100}\n")

    # ==========================================
    # 📥 NẠP DỮ LIỆU + CHẤM ĐIỂM
    # ==========================================
    def inject_new_data(self, phien: int, dice: list, tong: int):
        actual_full         = "TÀI" if tong > 10 else "XỈU"
        actual_label        = 'T' if tong > 10 else 'X'
        self.last_data_time = time.time()

        data = self.load_data()
        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': actual_full})
        self.save_data(data)

        if self.last_final_pred is not None and self.predicted_session_id == phien:
            self.total_played += 1
            self.tune_counter += 1
            wr_now = (self.total_won / self.total_played) * 100

            won = self.last_final_pred == actual_full
            if won:
                self.total_won += 1
                wr_now = (self.total_won / self.total_played) * 100
                print(f"💰 Ván {phien} HÚP {actual_full}!  WR: {self.total_won}/{self.total_played} ({wr_now:.1f}%)")
            else:
                print(f"💀 Ván {phien} GÃY!  WR: {self.total_won}/{self.total_played} ({wr_now:.1f}%)")

            # --- Update meta-learner ---
            if self.last_engine_preds is not None:
                self.meta.update(self.last_engine_preds, actual_label)

            # --- Optuna background mỗi 15 ván ---
            if self.tune_counter >= 15:
                self.tune_counter = 0
                snapshot = list(data)
                threading.Thread(
                    target=self.run_optuna_tuning,
                    args=(snapshot,),
                    daemon=True,
                    name="OptunaThread"
                ).start()

            # --- Bait matrix update ---
            current_wr = (self.total_won / self.total_played * 100) if self.total_played > 0 else 50.0
            nguong     = 4  

            if self.last_raw_key is not None and self.last_raw_bucket is not None:
                raw_correct = (self.last_raw_pred == actual_full)
                mk          = self.last_raw_key
                bk          = self.last_raw_bucket
                streak      = self.bucket_streaks[mk][bk]

                if not self.bait_matrix[mk][bk]:
                    if not raw_correct:
                        streak['loss'] += 1
                        streak['win']   = 0
                        if streak['loss'] >= nguong:
                            self.bait_matrix[mk][bk] = True
                            streak['loss']           = 0
                            print(f"🚨 [MA TRẬN] {mk} {bk}% GÃY {nguong} lần → BẬT BẺ CẦU.")
                    else:
                        streak['loss'] = 0
                else:
                    if raw_correct:
                        streak['win']  += 1
                        streak['loss']  = 0
                        if streak['win'] >= 2:
                            self.bait_matrix[mk][bk] = False
                            streak['win']            = 0
                            print(f"✅ [MA TRẬN] {mk} {bk}% ổn định → TẮT BẺ CẦU.")
                    else:
                        streak['win'] = 0

        elif self.predicted_session_id is not None and self.predicted_session_id != phien:
            print(
                f"⚠️ [LỆCH PHIÊN] Dự đoán cho {self.predicted_session_id} "
                f"nhưng nhận {phien} — bỏ qua chấm điểm."
            )

        return len(data)

    # ==========================================
    # 🔄 VÒNG LẶP CHÍNH
    # ==========================================
    def run(self):
        print("🚀 Khởi động SUNWIN AI v8 — ADAPTIVE BAYESIAN ENSEMBLE + META-LEARNING...")
        print("   7 Engine: Markov-BIC | N-gram-Chi2 | Hazard | EMA-Momentum |")
        print("             Tong-Zscore | Fourier | Regime-Detector")
        retry_delay = 2.0

        while True:
            try:
                res      = requests.get(API_ENDPOINT, headers=HEADERS, timeout=10)
                res.raise_for_status()
                api_data = res.json()

                if not api_data.get("Phien"):
                    time.sleep(retry_delay)
                    continue

                curr_session = int(api_data["Phien"])

                if curr_session != self.last_session_id:
                    self.last_session_id = curr_session
                    dice = [
                        int(api_data["Xuc_xac_1"]),
                        int(api_data["Xuc_xac_2"]),
                        int(api_data["Xuc_xac_3"])
                    ]
                    tong   = int(api_data["Tong"])
                    tx_str = "TÀI" if tong > 10 else "XỈU"

                    print(f"\n✅ PHIÊN {curr_session} | Tổng: {tong} ({tx_str}) | Xúc xắc: {dice}")
                    self.inject_new_data(curr_session, dice, tong)
                    self.analyze_next_round(curr_session + 1)

                retry_delay         = 2.0
                self.api_fail_count = 0

            except requests.exceptions.Timeout:
                self.api_fail_count += 1
                print(f"⏰ [API] Timeout #{self.api_fail_count}. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 60.0)

            except requests.exceptions.ConnectionError as e:
                self.api_fail_count += 1
                print(f"🔌 [API] Mất kết nối #{self.api_fail_count}. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 60.0)

            except requests.exceptions.HTTPError as e:
                self.api_fail_count += 1
                status = e.response.status_code if e.response else "?"
                print(f"❌ [API] HTTP {status} #{self.api_fail_count}. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 120.0)

            except requests.exceptions.JSONDecodeError:
                self.api_fail_count += 1
                print(f"⚠️ [API] Phản hồi không phải JSON. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 30.0)

            except KeyError as e:
                print(f"⚠️ [API] Thiếu field {e}. Tiếp tục...")
                time.sleep(2.0)

            except Exception as e:
                self.api_fail_count += 1
                print(f"❌ [LỖI] {type(e).__name__}: {e}. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 30.0)

            time.sleep(2)


# ==========================================
# 🚀 ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(
        target=lambda: SunwinLogic_v8().run(),
        daemon=True,
        name="MainLogicThread"
    ).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

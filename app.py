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
PATTERN_LEN  = 8   # ← chuỗi TX 8 ký tự là đơn vị chính

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
    return "🔥 SUNWIN AI v9 — TX-8GRAM PATTERN ENGINE ACTIVE"

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
    """Entropy Shannon — đo mức độ ngẫu nhiên của chuỗi TX."""
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
    """
    Wald–Wolfowitz runs test.
    p-value thấp (< 0.05) → chuỗi CÓ cấu trúc thực.
    """
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
    """Tương quan bậc 1 — đo mức độ ván sau liên quan ván trước."""
    s   = [1 if c == 'T' else 0 for c in seq[-window:]]
    if len(s) < 5:
        return 0.0
    a   = np.array(s[:-1], dtype=float)
    b   = np.array(s[1:],  dtype=float)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])

def pattern_entropy_8(seq: list) -> float:
    """
    Entropy của phân phối chuỗi 8 ký tự.
    Thấp → ít pattern khác nhau → dự đoán dễ hơn.
    Cao → nhiều pattern đa dạng → khó dự đoán.
    """
    if len(seq) < PATTERN_LEN + 5:
        return 1.0
    counter = collections.Counter()
    for i in range(len(seq) - PATTERN_LEN):
        counter[tuple(seq[i:i + PATTERN_LEN])] += 1
    total = sum(counter.values())
    if total == 0:
        return 1.0
    ent = 0.0
    for cnt in counter.values():
        p    = cnt / total
        ent -= p * math.log2(p + 1e-12)
    max_ent = PATTERN_LEN  # log2(2^8) = 8
    return min(1.0, ent / max_ent)


# ==========================================
# 🧠 ENGINE 1: 8-GRAM EXACT PATTERN MATCH
# ==========================================
def engine_8gram_exact(seq: list) -> tuple:
    """
    ENGINE CHÍNH — dùng chuỗi TX 8 ký tự gần nhất làm key.
    Tra cứu trong lịch sử: sau pattern này kết quả là T hay X?

    Ưu điểm:
    - Tối đa context (8 ký tự)
    - Cực kỳ chính xác khi có đủ mẫu
    - Không dùng tổng điểm

    Trả về (p_tai, confidence)
    """
    if len(seq) < PATTERN_LEN + 3:
        return 0.5, 0.0

    current_pattern = tuple(seq[-PATTERN_LEN:])
    search = seq[-(HISTORY_MAX):] if len(seq) > HISTORY_MAX else seq

    t_cnt = 0
    x_cnt = 0

    for i in range(len(search) - PATTERN_LEN):
        if tuple(search[i:i + PATTERN_LEN]) == current_pattern:
            nxt = search[i + PATTERN_LEN]
            if nxt == 'T':
                t_cnt += 1
            else:
                x_cnt += 1

    total = t_cnt + x_cnt
    if total == 0:
        return 0.5, 0.0

    # Laplace smoothing
    p_t  = (t_cnt + 1) / (total + 2)
    # Confidence: cần ít nhất 5 mẫu để tin tưởng
    conf = min(1.0, total / 10.0) * abs(p_t - 0.5) * 2.0

    return p_t, conf


# ==========================================
# 🧠 ENGINE 2: MULTI-ORDER 8-GRAM NGRAM SCAN
# ==========================================
def engine_ngram_scan(seq: list) -> tuple:
    """
    Quét tất cả n-gram từ bậc 8 xuống 3.
    Tại mỗi bậc: kiểm tra chi-square significance.
    Trả về bậc đầu tiên có p-value < 0.15.

    Khác Engine 1: Engine 1 chỉ dùng đúng 8 ký tự.
    Engine 2 tìm bậc tốt nhất (3-8).
    """
    if len(seq) < 5:
        return 0.5, 0.0

    search = seq[-300:]

    # Thống kê nền: tổng phân phối T/X
    all_t = sum(1 for c in search if c == 'T')
    all_x = len(search) - all_t
    total_all = all_t + all_x
    if total_all == 0:
        return 0.5, 0.0

    best_p_t   = 0.5
    best_conf  = 0.0
    best_pval  = 1.0

    for n in range(PATTERN_LEN, 2, -1):
        if len(search) <= n + 2:
            continue
        pattern = tuple(search[-n:])
        t_cnt, x_cnt = 0, 0

        for i in range(len(search) - n):
            if tuple(search[i:i + n]) == pattern:
                if search[i + n] == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total < 4:
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
            # Ưu tiên n cao hơn (bậc cao = context dài hơn = chính xác hơn)
            adjusted_conf = conf * (1.0 + (n - 3) * 0.05)
            if pval < best_pval or adjusted_conf > best_conf:
                best_pval  = pval
                best_p_t   = p_t
                best_conf  = adjusted_conf
                break  # Lấy bậc cao nhất có ý nghĩa

    return best_p_t, min(1.0, best_conf)


# ==========================================
# 🧠 ENGINE 3: MARKOV ĐA BẬC + BIC MODEL SELECTION
# ==========================================
def engine_markov_bic(seq: list, max_order: int = 8) -> tuple:
    """
    Chọn bậc Markov tối ưu qua BIC (Bayesian Information Criterion).
    Bậc tối đa nâng lên 8 (thay vì 6 ở v8) để tận dụng 8-char context.
    """
    if len(seq) < 5:
        return 0.5, 0.0

    search = seq[-300:]
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
# 🧠 ENGINE 4: STREAK HAZARD RATE
# ==========================================
def engine_streak_hazard(seq: list) -> tuple:
    """
    Hazard rate model: P(bẻ cầu | đã bệt k ván).
    Xây dựng empirical survival curve từ lịch sử thực.
    """
    if len(seq) < 5:
        return 0.5, 0.0

    last   = seq[-1]
    streak = 0
    for c in reversed(seq):
        if c == last:
            streak += 1
        else:
            break

    if streak < 1:
        return 0.5, 0.0

    hazard = {}
    search = seq[:-streak] if streak < len(seq) else seq
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

    k    = min(streak, 10)
    rev_count, cont_count = 0, 0
    for step in range(max(1, k - 1), k + 2):
        if step in hazard:
            rev_count  += hazard[step][0]
            cont_count += hazard[step][1]

    total = rev_count + cont_count
    if total < 3:
        p_rev = min(0.5 + streak * 0.04, 0.75)
        conf  = 0.2
    else:
        p_rev = (rev_count + 1) / (total + 2)
        conf  = min(1.0, total / 10.0) * abs(p_rev - 0.5) * 2.0

    p_tai = (1.0 - p_rev) if last == 'T' else p_rev
    return p_tai, conf


# ==========================================
# 🧠 ENGINE 5: WEIGHTED EMA + MOMENTUM
# ==========================================
def engine_ema_momentum(seq: list) -> tuple:
    """
    EMA ngắn (α=0.35) và dài (α=0.10):
    Momentum = EMA_short - EMA_long → lean theo xu hướng.
    """
    if len(seq) < 5:
        return 0.5, 0.0

    window = seq[-80:]
    vals   = [1.0 if c == 'T' else 0.0 for c in window]

    ema_s = 0.5
    for v in vals:
        ema_s = 0.35 * v + 0.65 * ema_s

    ema_l = 0.5
    for v in vals:
        ema_l = 0.10 * v + 0.90 * ema_l

    momentum = ema_s - ema_l
    p_tai    = _sigmoid(momentum * 8.0)
    conf     = min(1.0, abs(momentum) * 5.0)

    return p_tai, conf


# ==========================================
# 🧠 ENGINE 6: FOURIER PERIODICITY DETECTOR
# ==========================================
def engine_fourier_period(seq: list) -> tuple:
    """
    FFT trên chuỗi TX để phát hiện chu kỳ ẩn.
    Nếu dominant frequency chiếm > 12% tổng power → dự đoán theo pha.
    """
    if len(seq) < 20:
        return 0.5, 0.0

    window   = seq[-128:]
    arr      = np.array([1.0 if c == 'T' else -1.0 for c in window])

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

    period       = 1.0 / (freqs[dom_idx] + 1e-9)
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
# 🧠 ENGINE 7: REGIME DETECTOR (HOT/COLD/CHOP)
# ==========================================
def engine_regime(seq: list) -> tuple:
    """
    Phân loại regime hiện tại của game.
    3 cửa sổ (5, 15, 30 ván) để xác nhận chéo.
    """
    if len(seq) < 10:
        return 0.5, 0.0

    def freq_t(window):
        s = seq[-window:] if len(seq) >= window else seq
        return sum(1 for c in s if c == 'T') / len(s)

    def chop_rate(window):
        s = seq[-window:] if len(seq) >= window else seq
        return sum(1 for i in range(1, len(s)) if s[i] != s[i-1]) / max(1, len(s) - 1)

    f5, f15, f30 = freq_t(5), freq_t(15), freq_t(30)
    c5, c15      = chop_rate(5), chop_rate(15)

    if c5 > 0.70 and c15 > 0.65:
        last  = seq[-1]
        p_tai = 0.28 if last == 'T' else 0.72
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
# 🧠 ENGINE 8: 8-GRAM PATTERN DISTRIBUTION (WEIGHTED)
# ==========================================
def engine_8gram_distribution(seq: list) -> tuple:
    """
    Phân tích toàn bộ phân phối hậu duệ (successor distribution) của chuỗi 8 ký tự.
    Khác Engine 1: dùng Bayesian posterior thay vì đếm đơn giản.
    Nếu context hiếm gặp → fallback về phân phối context ngắn hơn dần dần.

    Bayesian hierarchical approach:
    - Prior: phân phối T/X toàn cục
    - Likelihood: P(T|8gram) từ data
    - Posterior: kết hợp
    """
    if len(seq) < PATTERN_LEN + 5:
        return 0.5, 0.0

    search     = seq[-400:]
    global_t   = sum(1 for c in search if c == 'T')
    global_n   = len(search)
    global_p_t = global_t / global_n if global_n > 0 else 0.5

    # Hierarchical: thử từ 8 xuống 4
    for n in range(PATTERN_LEN, 3, -1):
        if len(search) <= n + 2:
            continue
        ctx   = tuple(search[-n:])
        t_cnt = 0
        x_cnt = 0
        for i in range(len(search) - n):
            if tuple(search[i:i + n]) == ctx:
                nxt = search[i + n]
                if nxt == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total < 2:
            continue

        # Bayesian posterior với prior = global_p_t, strength = 4
        prior_strength = 4.0
        p_t_post = (t_cnt + prior_strength * global_p_t) / (total + prior_strength)

        # Confidence: dựa vào tổng mẫu và độ lệch
        conf = min(1.0, total / 8.0) * abs(p_t_post - 0.5) * 2.0 * (n / PATTERN_LEN)

        if conf > 0.05:
            return p_t_post, conf

    return global_p_t, 0.10


# ==========================================
# 🧠 ENGINE 9: TRANSITION MATRIX (8 BƯỚC)
# ==========================================
def engine_transition_matrix(seq: list) -> tuple:
    """
    Xây dựng transition matrix đầy đủ từ 8 ký tự trước.
    Mỗi state là một tuple 8 ký tự (2^8 = 256 state có thể).
    Tính xác suất chuyển đổi sang T hoặc X.

    Đây là Markov bậc 8 thuần túy — khác BIC engine ở chỗ
    không cố gắng tìm bậc tối ưu mà cố định bậc 8.
    """
    if len(seq) < PATTERN_LEN + 10:
        return 0.5, 0.0

    search = seq[-400:]
    table  = {}  # {(8-gram): [t_count, x_count]}

    for i in range(len(search) - PATTERN_LEN):
        key = tuple(search[i:i + PATTERN_LEN])
        nxt = search[i + PATTERN_LEN]
        if key not in table:
            table[key] = [0, 0]
        if nxt == 'T':
            table[key][0] += 1
        else:
            table[key][1] += 1

    current_key = tuple(seq[-PATTERN_LEN:])

    if current_key not in table:
        return 0.5, 0.0

    t_cnt, x_cnt = table[current_key]
    total        = t_cnt + x_cnt

    if total < 2:
        return 0.5, 0.0

    p_t  = (t_cnt + 1) / (total + 2)
    conf = min(1.0, total / 8.0) * abs(p_t - 0.5) * 2.0

    return p_t, conf


# ==========================================
# 🧠 ENGINE 10: POSITION-AWARE 8-GRAM VOTING
# ==========================================
def engine_position_voting(seq: list) -> tuple:
    """
    Xét 8 ký tự = 8 vị trí. Mỗi vị trí bỏ phiếu độc lập.
    Vị trí i: P(T | seq[-8+i]) — đây là "marginal" effect của từng vị trí.
    Kết hợp bằng weighted vote (vị trí gần hơn = weight cao hơn).

    Ý nghĩa: "Ký tự ở vị trí nào trong 8 ký tự quan trọng nhất?"
    """
    if len(seq) < PATTERN_LEN + 10:
        return 0.5, 0.0

    search  = seq[-300:]
    weights = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.5, 5.0]  # Gần hơn = weight cao hơn

    log_odds_sum = 0.0
    weight_sum   = 0.0

    for pos in range(PATTERN_LEN):
        target_val = seq[-(PATTERN_LEN - pos)]  # ký tự tại vị trí pos trong 8 ký tự cuối
        t_cnt      = 0
        x_cnt      = 0

        for i in range(len(search) - PATTERN_LEN):
            if search[i + pos] == target_val:
                nxt = search[i + PATTERN_LEN]
                if nxt == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total < 5:
            continue

        p_t  = (t_cnt + 1) / (total + 2)
        w    = weights[pos]
        lo   = _to_log_odds(p_t)
        log_odds_sum += w * lo
        weight_sum   += w

    if weight_sum == 0:
        return 0.5, 0.0

    p_tai = _sigmoid(log_odds_sum / weight_sum * 0.5)
    conf  = min(1.0, abs(p_tai - 0.5) * 2.5) * 0.6

    return p_tai, conf


# ==========================================
# 🧠 META-LEARNER — ONLINE LEARNING với EXP DECAY
# ==========================================
class MetaLearner:
    """
    Theo dõi độ chính xác của từng engine theo rolling window.
    Dùng exponential decay: ván gần đây quan trọng hơn ván cũ.
    """
    def __init__(self, n_engines: int = 10, window: int = 40, decay: float = 0.93):
        self.n         = n_engines
        self.window    = window
        self.decay     = decay
        # (correct: bool, weight: float)
        self.histories = [collections.deque(maxlen=window) for _ in range(n_engines)]

    def update(self, engine_preds: list, actual: str):
        """Ghi kết quả đúng/sai cho từng engine với weight theo thứ tự thời gian."""
        # Decay existing weights
        for hist in self.histories:
            new_hist = collections.deque(maxlen=self.window)
            for correct, w in hist:
                new_hist.append((correct, w * self.decay))
            hist.clear()
            hist.extend(new_hist)

        for i, p in enumerate(engine_preds):
            pred_label = 'T' if p >= 0.5 else 'X'
            correct    = 1 if pred_label == actual else 0
            self.histories[i].append((correct, 1.0))  # mới nhất weight = 1.0

    def get_accuracy_weights(self) -> list:
        """
        Trả về trọng số bổ sung cho mỗi engine dựa trên accuracy có weight decay.
        Engine ≥65% acc → bonus; < 40% → penalty.
        """
        weights = []
        for hist in self.histories:
            if len(hist) < 5:
                weights.append(1.0)
            else:
                total_w  = sum(w for _, w in hist)
                total_c  = sum(c * w for c, w in hist)
                acc      = total_c / total_w if total_w > 0 else 0.5
                # Smooth mapping: 70%→1.5, 50%→0.9, 30%→0.5
                w = 0.1 + acc * 1.6
                weights.append(round(max(0.3, min(2.0, w)), 3))
        return weights


# ==========================================
# 🧠 ADAPTIVE BAYESIAN ENSEMBLE — 10 ENGINE
# ==========================================
def adaptive_bayesian_combine(
    engine_results: list,
    base_weights: list,
    meta_weights: list,
    entropy: float,
    runs_pval: float,
    autocorr: float,
    pat_entropy_8: float
) -> tuple:
    """
    Kết hợp 10 engine với:
    1. Base weights (Optuna-tuned)
    2. Engine confidence (tự báo cáo)
    3. Meta-learning weights (exp-decay accuracy)
    4. Entropy scaling — chuỗi ngẫu nhiên → thu về 50/50
    5. Runs test penalty — random → giảm signal
    6. Autocorrelation bias
    7. Pattern entropy penalty — quá nhiều pattern khác nhau → giảm tin

    Trả về (p_tai_final, overall_confidence)
    """
    # --- Entropy scale ---
    if entropy > 0.92:
        entropy_scale = 0.20
    elif entropy > 0.80:
        entropy_scale = 0.45
    elif entropy > 0.65:
        entropy_scale = 0.72
    else:
        entropy_scale = 1.0

    # --- Runs test scale ---
    runs_scale = 1.0 - max(0.0, runs_pval - 0.20) * 0.75

    # --- Pattern entropy scale (8-gram đa dạng quá → khó predict) ---
    pat_scale = 1.0 - max(0.0, pat_entropy_8 - 0.60) * 0.5

    combined_scale = entropy_scale * runs_scale * pat_scale

    log_odds_sum  = 0.0
    weight_sum    = 0.0
    conf_weighted = 0.0

    for i, (p_tai, conf) in enumerate(engine_results):
        bw    = base_weights[i] if i < len(base_weights) else 1.0
        mw    = meta_weights[i] if i < len(meta_weights) else 1.0
        eff_w = bw * mw * max(0.25, conf + 0.35)

        lo            = _to_log_odds(p_tai)
        log_odds_sum  += eff_w * combined_scale * lo
        weight_sum    += eff_w
        conf_weighted += eff_w * conf

    if weight_sum == 0:
        return 0.5, 0.0

    # Autocorrelation bias
    if abs(autocorr) > 0.08:
        autocorr_lo   = autocorr * 0.35
        log_odds_sum += autocorr_lo * combined_scale

    p_tai_final = _sigmoid(log_odds_sum)
    avg_conf    = conf_weighted / weight_sum * combined_scale
    avg_conf    = max(0.0, min(1.0, avg_conf))

    return p_tai_final, avg_conf


# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH v9
# ==========================================
class SunwinLogic_v9:
    def __init__(self):
        self.last_session_id      = None
        self.total_played         = 0
        self.total_won            = 0
        self.last_final_pred      = None
        self.predicted_session_id = None
        self.history_predictions  = {}
        self.tune_counter         = 0

        # --- BASE WEIGHTS 10 ENGINE ---
        # Thứ tự: 8gram_exact, ngram_scan, markov_bic, streak_hazard,
        #         ema_momentum, fourier, regime, 8gram_dist, transition_matrix, position_voting
        self.weights = [
            4.0,   # E1: 8gram exact (engine chính)
            3.0,   # E2: ngram scan chi-square
            2.5,   # E3: Markov BIC
            1.8,   # E4: Streak hazard
            1.2,   # E5: EMA momentum
            0.7,   # E6: Fourier
            1.5,   # E7: Regime
            3.5,   # E8: 8gram distribution Bayesian
            3.0,   # E9: Transition matrix bậc 8
            2.0,   # E10: Position voting
        ]

        # --- META-LEARNER (10 engine, window=40, decay=0.93) ---
        self.meta = MetaLearner(n_engines=10, window=40, decay=0.93)

        # --- STATE ---
        self.last_engine_preds = None
        self.last_raw_pred     = None
        self.last_raw_key      = None
        self.last_raw_bucket   = None

        # --- BAIT MATRIX ---
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
    # ⚙️ OPTUNA — Tối ưu 10 base weights
    # ==========================================
    def run_optuna_tuning(self, data: list):
        if len(data) < 40:
            return
        print("\n🔄 [OPTUNA] Tối ưu 10 base weights (8-gram centric)...")

        def objective(trial):
            ws = [
                trial.suggest_float('w0', 1.0, 8.0),   # 8gram exact
                trial.suggest_float('w1', 0.5, 6.0),   # ngram scan
                trial.suggest_float('w2', 0.5, 5.0),   # Markov BIC
                trial.suggest_float('w3', 0.2, 4.0),   # Streak hazard
                trial.suggest_float('w4', 0.1, 3.0),   # EMA momentum
                trial.suggest_float('w5', 0.0, 2.0),   # Fourier
                trial.suggest_float('w6', 0.2, 3.5),   # Regime
                trial.suggest_float('w7', 1.0, 7.0),   # 8gram distribution
                trial.suggest_float('w8', 1.0, 7.0),   # Transition matrix
                trial.suggest_float('w9', 0.5, 4.0),   # Position voting
            ]

            test_len = min(40, len(data) - REQUIRED_LEN)
            correct  = 0

            for i in range(len(data) - test_len, len(data)):
                past = data[:i]
                if len(past) < REQUIRED_LEN:
                    continue

                seq           = ["T" if x['tong'] > 10 else "X" for x in past[-400:]]
                entropy       = shannon_entropy(seq)
                runs_pval     = runs_test_pvalue(seq)
                autocorr      = autocorrelation_lag1(seq)
                pat_ent8      = pattern_entropy_8(seq)

                results = [
                    engine_8gram_exact(seq),
                    engine_ngram_scan(seq),
                    engine_markov_bic(seq),
                    engine_streak_hazard(seq),
                    engine_ema_momentum(seq),
                    engine_fourier_period(seq),
                    engine_regime(seq),
                    engine_8gram_distribution(seq),
                    engine_transition_matrix(seq),
                    engine_position_voting(seq),
                ]
                meta_ws  = [1.0] * 10
                p_tai, _ = adaptive_bayesian_combine(
                    results, ws, meta_ws, entropy, runs_pval, autocorr, pat_ent8
                )
                pred   = "TÀI" if p_tai >= 0.5 else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1

            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=100)

        best         = study.best_params
        self.weights = [round(best[f'w{i}'], 3) for i in range(10)]
        names        = ["8Gram","Ngram","Markov","Streak","EMA","Fourier","Regime","8GramBayes","TransMatrix","PosVote"]
        w_str        = " | ".join(f"{n}={w}" for n, w in zip(names, self.weights))
        print(f"✅ [OPTUNA] Xong! {w_str}\n")

    # ==========================================
    # 🧮 PHÂN TÍCH & DỰ ĐOÁN
    # ==========================================
    def analyze_next_round(self, next_session_id: int):
        data = self.load_data()

        print(f"\n{'='*110}")
        print(f"🎯 PHÂN TÍCH PHIÊN {next_session_id}")
        print(f"{'='*110}")

        if len(data) < REQUIRED_LEN:
            msg = f"Thu thập dữ liệu: {len(data)}/{REQUIRED_LEN} ván..."
            print(f"⚠️ {msg}")
            self.sync_to_dashboard(next_session_id, "WAIT", msg)
            return

        # Build chuỗi TX — chỉ dùng TX, không dùng tong để predict
        seq = ["T" if x['tong'] > 10 else "X" for x in data[-400:]]

        # --- CHUỖI 8 KÝ TỰ GẦN NHẤT ---
        last_8 = "".join(seq[-PATTERN_LEN:]) if len(seq) >= PATTERN_LEN else "".join(seq)

        # --- PHÂN TÍCH THỐNG KÊ ---
        entropy    = shannon_entropy(seq, window=40)
        runs_pval  = runs_test_pvalue(seq)
        autocorr   = autocorrelation_lag1(seq)
        pat_ent8   = pattern_entropy_8(seq)

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

        ac_label = (
            "dương (+tiếp diễn)" if autocorr > 0.05
            else "âm (+xen kẽ)"  if autocorr < -0.05
            else "trung tính"
        )

        # --- CHẠY 10 ENGINE ---
        r1  = engine_8gram_exact(seq)
        r2  = engine_ngram_scan(seq)
        r3  = engine_markov_bic(seq)
        r4  = engine_streak_hazard(seq)
        r5  = engine_ema_momentum(seq)
        r6  = engine_fourier_period(seq)
        r7  = engine_regime(seq)
        r8  = engine_8gram_distribution(seq)
        r9  = engine_transition_matrix(seq)
        r10 = engine_position_voting(seq)

        engine_results = [r1, r2, r3, r4, r5, r6, r7, r8, r9, r10]

        # --- META-LEARNING WEIGHTS ---
        meta_ws = self.meta.get_accuracy_weights()
        w10     = self.weights[:10]

        # --- TỔNG HỢP ---
        p_tai, overall_conf = adaptive_bayesian_combine(
            engine_results, w10, meta_ws,
            entropy, runs_pval, autocorr, pat_ent8
        )
        p_xiu = 1.0 - p_tai

        # --- CHỐT GỐC ---
        chot_goc     = "TÀI" if p_tai >= 0.5 else "XỈU"
        conf_percent = round(max(p_tai, p_xiu) * 100.0, 1)
        matrix_key   = chot_goc
        bucket       = self.get_confidence_bucket(conf_percent)
        current_wr   = (self.total_won / self.total_played * 100) if self.total_played > 0 else 50.0

        # --- LOG ---
        E_NAMES = [
            "8Gram Exact (8 ký tự)    ",
            "NGram Scan Chi-sq (3-8)  ",
            "Markov BIC (bậc 1-8)     ",
            "Streak Hazard Rate       ",
            "EMA Momentum (S/L cross) ",
            "Fourier Periodicity      ",
            "Regime Detector (H/C/Ch) ",
            "8Gram Bayesian Posterior ",
            "Transition Matrix (bậc8) ",
            "Position Voting (8 vị trí)",
        ]

        combined_s = max(0.20, (1.0 - entropy * 0.7)) * (1.0 - max(0.0, runs_pval - 0.20) * 0.75)

        print(f"")
        print(f"📌 CHUỖI TX 8 KÝ TỰ GẦN NHẤT: [{last_8}]")
        print(f"")
        print(f"📊 PHÂN TÍCH THỐNG KÊ:")
        print(f"   Entropy (40v)      : {entropy:.4f}  → {ent_label}")
        print(f"   Runs test          : p={runs_pval:.3f}  → {runs_label}")
        print(f"   Autocorr lag-1     : r={autocorr:+.3f}  → {ac_label}")
        print(f"   Pattern entropy 8g : {pat_ent8:.4f}  → {'🔴 cao (đa dạng)' if pat_ent8 > 0.7 else '🟢 thấp (lặp lại)'}")
        print(f"   Signal scale       : {combined_s:.3f}")
        print(f"")
        print(f"📘 10 ENGINE — P(TÀI) | Conf | MetaW | BaseW")
        for i, ((p, c), name) in enumerate(zip(engine_results, E_NAMES)):
            mw    = meta_ws[i] if i < len(meta_ws) else 1.0
            bw    = w10[i]     if i < len(w10)     else 1.0
            bar_t = "█" * int(p * 20)
            bar_x = "░" * (20 - int(p * 20))
            label = "TÀI" if p >= 0.5 else "XỈU"
            print(f"   E{i+1:02d} {name}: {p*100:5.1f}% [{bar_t}{bar_x}] {label} "
                  f"conf={c:.2f} meta={mw:.2f} base={bw}")
        print(f"")
        print(f"   ─── ADAPTIVE BAYESIAN ENSEMBLE (10 ENGINE) ───")
        print(f"   => P(TÀI) = {p_tai*100:.2f}%  |  P(XỈU) = {p_xiu*100:.2f}%")
        print(f"   => Overall confidence = {overall_conf:.3f}")
        print(f"   => CHỐT GỐC : {chot_goc} ({conf_percent}%)  [Bucket {bucket}%]")

        # --- BAIT MATRIX ---
        nguong    = 4 if current_wr >= 55 else 3
        note      = ""
        chot_cuoi = chot_goc

        if self.bait_matrix[matrix_key][bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note      = f"⚠️ {matrix_key} {bucket}% đang lừa → ÉP BẺ → {chot_cuoi}"
        else:
            note = "✅ Vào theo 8-Gram Adaptive Bayesian"

        # --- LƯU TRẠNG THÁI ---
        self.last_engine_preds    = [p for p, _ in engine_results]
        self.last_raw_pred        = chot_goc
        self.last_raw_key         = matrix_key
        self.last_raw_bucket      = bucket
        self.last_final_pred      = chot_cuoi
        self.history_predictions[str(next_session_id)] = chot_cuoi
        self.predicted_session_id = next_session_id

        wr_str = f" [WR: {self.total_won}/{self.total_played} = {current_wr:.1f}%]" if self.total_played > 0 else ""
        print(f"{'─'*110}")
        print(f"🔥 LỆNH CHỐT CUỐI : VÀO {chot_cuoi}  ← {note}{wr_str}")

        detail = (
            f"TX-8Gram {chot_goc}({conf_percent:.1f}%) "
            f"H={entropy:.2f} p8={last_8} → {note}"
        )
        self.sync_to_dashboard(next_session_id, chot_cuoi, detail)
        print(f"{'='*110}\n")

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

            won = self.last_final_pred == actual_full
            if won:
                self.total_won += 1
                wr_now = (self.total_won / self.total_played) * 100
                print(f"💰 Ván {phien} HÚP {actual_full}!  WR: {self.total_won}/{self.total_played} ({wr_now:.1f}%)")
            else:
                wr_now = (self.total_won / self.total_played) * 100
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
            nguong     = 4 if current_wr >= 55 else 3

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
        print("🚀 Khởi động SUNWIN AI v9 — TX-8GRAM ADAPTIVE BAYESIAN ENSEMBLE")
        print("   10 Engine: 8Gram-Exact | NGram-Chi2 | Markov-BIC(1-8) | Streak-Hazard |")
        print("             EMA-Momentum | Fourier | Regime | 8Gram-Bayes | TransMatrix8 | PosVoting")
        print("   Meta: Online learning với exponential decay")
        print("   Optuna: Auto-tune 10 weights mỗi 15 ván")
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

                    print(f"\n✅ PHIÊN {curr_session} | {tx_str} (tong={tong}) | Xúc xắc: {dice}")
                    self.inject_new_data(curr_session, dice, tong)
                    self.analyze_next_round(curr_session + 1)

                retry_delay         = 2.0
                self.api_fail_count = 0

            except requests.exceptions.Timeout:
                self.api_fail_count += 1
                print(f"⏰ [API] Timeout #{self.api_fail_count}. Retry {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 60.0)

            except requests.exceptions.ConnectionError:
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
        target=lambda: SunwinLogic_v9().run(),
        daemon=True,
        name="MainLogicThread"
    ).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

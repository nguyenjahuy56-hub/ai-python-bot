import time
import requests
import json
import os
import sys
import threading
import math
import optuna
from pymongo import MongoClient
from flask import Flask

# Tắt log rác của Optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️ CONFIG HỆ THỐNG & THÔNG TIN XÁC THỰC
# ==========================================
API_ENDPOINT  = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"
MONGO_URI     = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"

USER_AUTH_DATA = {
    "accessToken":    "d93b0a3da4204530bbf97944c5353348",
    "refreshToken":   "a48b8445b47545e8bf55b5ebcdd303c5.fd44c0a6c99b455c84c845298d835679",
    "wsToken":        "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJnZW5kZXIiOjAsImNhblZpZXdTdGF0IjpmYWxzZSwiZGlzcGxheU5hbWUiOiJzb25ndmVkZW0yMCIsImJvdCI6MCwiaXNNZXJjaGFudCI6ZmFsc2UsInZlcmlmaWVkQmFua0FjY291bnQiOnRydWUsInBsYXlFdmVudExvYmJ5IjpmYWxzZSwiY3VzdG9tZXJJZCI6MjM5OTUzMjE1LCJhZmZJZCI6ImRlZmF1bHQiLCJiYW5uZWQiOmZhbHNlLCJicmFuZCI6InN1bi53aW4iLCJlbWFpbCI6IiIsInRpbWVzdGFtcCI6MTc3ODA0MzQyMjAxNiwibG9ja0dhbWVzIjpbXSwiYW1vdW50IjowLCJsb2NrQ2hhdCI6ZmFsc2UsInBob25lVmVyaWZpZWQiOnRydWUsImlwQWRkcmVzcyI6IjExMy4xNzUuMTAwLjU3IiwibXV0ZSI6ZmFsc2UsImF2YXRhciI6Imh0dHBzOi8vaW1hZ2VzLnN3aW5zaG9wLm5ldC9pbWFnZXMvYXZhdGFyL2F2YXRhcl8xMC5wbmciLCJwbGF0Zm9ybUlkIjoyLCJ1c2VySWQiOiIwMDM3NDA2OC04YmZiLTQ5NTYtOWIxMi0yODkzYzMxMDcxNjAiLCJlbWFpbFZlcmlmaWVkIjpudWxsLCJyZWdUaW1lIjoxNzQ1NTkyNjU1ODA3LCJwaG9uZSI6Ijg0MzI5Njg5OTcxIiwiZGVwb3NpdCI6dHJ1ZSwidXNlcm5hbWUiOiJTQ19zb25ndmVkZW0xMCJ9.4jl_XtPCRLFuSOrBlfAtaSz3kg27oIqZFqcHwPv34G0",
    "signature":      "366DB52754A4C6B5AE4D3169940BE3BB2C046D859898F0B7E6BDFA3F84069E77B309CE8EE69EA0482776D271C521EDC2D223503CA0B182D6F8DB9E4C0E49C9514DF7418F284DF0AD4F603F23018D0914A225350B66C82C2A17FC2297CF27BF13D4DDE48E06427520B0A99BB8EC0EA3A6947FD1D255BE3AB92C66F0DD475EF5F9",
    "userId":         "00374068-8bfb-4956-9b12-2893c3107160",
    "username":       "SC_songvedem10"
}

HEADERS = {
    "Authorization": f"Bearer {USER_AUTH_DATA['accessToken']}",
    "wsToken":       USER_AUTH_DATA['wsToken'],
    "signature":     USER_AUTH_DATA['signature'],
    "Content-Type":  "application/json"
}

HISTORY_MAX  = 350   # Lưu tối đa 350 ván để engine Markov có đủ mẫu
REQUIRED_LEN = 20    # Cần ít nhất 20 ván để bắt đầu dự đoán

# ==========================================
# 🛠️ KẾT NỐI MONGODB
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
    return "🔥 AI Server v7 BAYESIAN — 6-ENGINE + WATCHDOG ACTIVE"

@app.route('/health')
def health():
    return json.dumps({"status": "ok", "time": time.time()})


# ==========================================
# 🔢 TIỆN ÍCH TOÁN HỌC
# ==========================================
def _sigmoid(x: float) -> float:
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))

def _to_log_odds(p: float) -> float:
    p = max(1e-7, min(1.0 - 1e-7, p))
    return math.log(p / (1.0 - p))

def shannon_entropy(seq: list, window: int = 30) -> float:
    """
    Shannon entropy: 1.0 = hoàn toàn ngẫu nhiên, 0.0 = pattern rõ ràng.
    Dùng để scale trọng số — khi ngẫu nhiên cao, giảm tin tưởng vào engine.
    """
    s = seq[-window:] if len(seq) >= window else seq
    if not s:
        return 1.0
    t = sum(1 for c in s if c == 'T')
    n = len(s)
    if t == 0 or t == n:
        return 0.0
    p = t / n
    return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)


# ==========================================
# 🧠 ENGINE 1: MARKOV CHAIN ĐA BẬC + BACKOFF + LAPLACE
# ==========================================
def engine_markov_chain(seq: list, max_order: int = 5) -> float:
    """
    Dùng chuỗi Markov bậc cao nhất có đủ mẫu (≥4 lần xuất hiện).
    Backoff từ bậc 5 → 1 cho đến khi tìm được.
    Laplace smoothing +1 để tránh chia cho 0.

    Đây là engine chủ lực — nắm bắt sự phụ thuộc có trí nhớ dài.
    """
    if len(seq) < 2:
        return 0.5

    # Giới hạn cửa sổ tìm kiếm để tránh chậm
    search = seq[-250:]

    for order in range(min(max_order, len(search) - 1), 0, -1):
        ctx = tuple(search[-order:])
        t_cnt, x_cnt = 0, 0

        for i in range(len(search) - order):
            if tuple(search[i:i + order]) == ctx:
                nxt = search[i + order]
                if nxt == 'T':
                    t_cnt += 1
                else:
                    x_cnt += 1

        total = t_cnt + x_cnt
        if total >= 4:
            # Laplace smoothing: cộng 1 vào cả hai phía
            return (t_cnt + 1) / (total + 2)

    # Fallback: tần suất thực trong 50 ván gần nhất
    win = seq[-50:]
    t = sum(1 for c in win if c == 'T')
    return (t + 1) / (len(win) + 2)


# ==========================================
# 🧠 ENGINE 2: N-GRAM PATTERN MATCHING (7→3 ký tự)
# ==========================================
def engine_ngram_pattern(seq: list) -> tuple:
    """
    Khớp mẫu N-gram từ dài nhất (7) xuống ngắn nhất (3).
    Dừng lại tại mẫu dài nhất có ≥3 lần khớp.
    Trả về (p_tai, confidence).
    confidence = độ tin cậy dựa trên số mẫu khớp được.
    """
    if len(seq) < 4:
        return 0.5, 0.0

    search = seq[-200:]

    for n in (7, 6, 5, 4, 3):
        if len(search) <= n:
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
        if total >= 3:
            p_t = (t_cnt + 1) / (total + 2)
            # confidence tuyến tính: 3 mẫu = 0.3, 10+ mẫu = 1.0
            conf = min(1.0, total / 10.0)
            return p_t, conf

    return 0.5, 0.0


# ==========================================
# 🧠 ENGINE 3: STREAK ANALYSIS THỰC NGHIỆM
# ==========================================
def engine_streak_analysis(seq: list) -> float:
    """
    Sau bệt N ván cùng chiều, tỉ lệ bẻ cầu thực tế từ lịch sử là bao nhiêu?
    Không dùng heuristic cứng — dùng đếm thực.

    Ví dụ: Sau 4 ván T liên tiếp, lịch sử cho thấy 60% bẻ sang X.
    """
    if len(seq) < 4:
        return 0.5

    last = seq[-1]

    # Đo độ dài bệt hiện tại
    streak_len = 0
    for c in reversed(seq):
        if c == last:
            streak_len += 1
        else:
            break

    if streak_len < 2:
        return 0.5   # Chưa bệt đủ để phân tích

    # Giới hạn streak_len để tránh quét quá ít mẫu
    k = min(streak_len, 5)

    rev_cnt  = 0   # Số lần bẻ cầu sau bệt k ván
    cont_cnt = 0   # Số lần tiếp tục sau bệt k ván

    for i in range(len(seq) - k - 1):
        # Kiểm tra bệt k ván tại vị trí i
        if all(seq[i + j] == last for j in range(k)):
            # Bệt phải bắt đầu đúng tại i (ký tự trước khác hoặc không có)
            if i == 0 or seq[i - 1] != last:
                nxt = seq[i + k]
                if nxt == last:
                    cont_cnt += 1
                else:
                    rev_cnt += 1

    total = rev_cnt + cont_cnt
    if total < 2:
        # Prior nhẹ: bệt ≥ 3 thì hơi nghiêng về bẻ
        p_reversal = 0.58 if streak_len >= 3 else 0.5
    else:
        p_reversal = (rev_cnt + 1) / (total + 2)

    # p_tai = P(ván tiếp theo là TÀI)
    return (1.0 - p_reversal) if last == 'T' else p_reversal


# ==========================================
# 🧠 ENGINE 4: EMA XU HƯỚNG (Exponential Moving Average)
# ==========================================
def engine_ema_trend(seq: list, alpha: float = 0.25) -> float:
    """
    EMA với alpha=0.25 → cửa sổ hiệu dụng ~7 ván.
    Nếu EMA > 0.5 → xu hướng TÀI, < 0.5 → xu hướng XỈU.
    Bổ sung nhỏ để đuổi theo momentum ngắn hạn.
    """
    if not seq:
        return 0.5

    ema = 0.5
    for c in seq[-60:]:
        v   = 1.0 if c == 'T' else 0.0
        ema = alpha * v + (1.0 - alpha) * ema

    return ema


# ==========================================
# 🧠 ENGINE 5: PHÂN PHỐI XÚC XẮC — HỒI QUY TRUNG BÌNH
# ==========================================
def engine_dice_regression(tong_list: list, window: int = 30) -> float:
    """
    3 xúc xắc: trung bình lý thuyết ≈ 10.5.
    Nếu gần đây liên tục cao (>10.5) → hơi lean về XỈU (hồi quy).
    Nếu liên tục thấp → hơi lean về TÀI.
    Đây là signal yếu nhất — chỉ cộng bổ sung nhỏ.
    """
    if len(tong_list) < 8:
        return 0.5

    recent     = tong_list[-window:]
    mean_r     = sum(recent) / len(recent)
    EXPECTED   = 10.5
    deviation  = (mean_r - EXPECTED) / 2.5   # normalize

    # deviation > 0 (mean cao) → hơi lean XỈU → p_tai giảm
    return _sigmoid(-deviation * 0.35)


# ==========================================
# 🧠 ENGINE 6: OSCILLATION DETECTOR (Cầu Rung)
# ==========================================
def engine_oscillation(seq: list) -> float:
    """
    Phát hiện chuỗi xen kẽ T-X-T-X (cầu rung).
    Nếu 5 ván cuối đều xen kẽ → đếm tần suất tiếp tục/phá vỡ trong lịch sử.
    """
    if len(seq) < 6:
        return 0.5

    last5 = seq[-5:]
    is_alternating = all(last5[i] != last5[i + 1] for i in range(4))

    if not is_alternating:
        return 0.5

    # Đếm lịch sử: sau chuỗi xen kẽ 5 ký tự, kết quả tiếp theo là gì?
    search = seq[-150:]
    t_cnt, x_cnt = 0, 0

    for i in range(len(search) - 5):
        block = search[i:i + 5]
        if all(block[j] != block[j + 1] for j in range(4)):
            nxt = search[i + 5]
            if nxt == 'T':
                t_cnt += 1
            else:
                x_cnt += 1

    total = t_cnt + x_cnt
    if total < 3:
        # Default prior: cầu rung tiếp tục xen kẽ → bẻ ký tự cuối
        last = seq[-1]
        return 0.28 if last == 'T' else 0.72

    return (t_cnt + 1) / (total + 2)


# ==========================================
# 🧠 KẾT HỢP BAYESIAN — LÕI TOÁN HỌC CHÍNH
# ==========================================
def bayesian_combine(engine_probs: list, weights: list, entropy: float) -> float:
    """
    Kết hợp 6 engine bằng log-odds framework.

    Cơ chế:
    1. Mỗi engine trả về P(TÀI) ∈ [0, 1].
    2. Chuyển sang log-odds: lo = log(p/(1-p))
    3. Nhân với trọng số engine (Optuna tối ưu).
    4. Scale theo entropy: entropy cao → scale xuống → kết quả về 50/50.
    5. Tổng hợp → chuyển lại thành xác suất cuối cùng.

    Entropy scale: entropy=1.0 (random) → scale=0.3; entropy=0.0 (pattern) → scale=1.0
    """
    entropy_scale = max(0.3, 1.0 - entropy * 0.7)

    log_odds_sum = 0.0
    for p, w in zip(engine_probs, weights):
        lo           = _to_log_odds(p)
        log_odds_sum += w * entropy_scale * lo

    return _sigmoid(log_odds_sum)


# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH
# ==========================================
class SunwinLogic_v7:
    def __init__(self):
        self.last_session_id      = None
        self.total_played         = 0
        self.total_won            = 0
        self.last_final_pred      = None
        self.predicted_session_id = None
        self.history_predictions  = {}
        self.tune_counter         = 0

        # --- TRỌNG SỐ 6 ENGINE (Optuna sẽ tối ưu liên tục) ---
        self.w_markov  = 2.5   # Engine 1 — Markov Chain (lõi chính)
        self.w_ngram   = 2.0   # Engine 2 — N-gram Pattern
        self.w_streak  = 1.5   # Engine 3 — Streak Analysis
        self.w_ema     = 0.8   # Engine 4 — EMA Trend
        self.w_dice    = 0.4   # Engine 5 — Dice Regression (signal yếu)
        self.w_osc     = 0.9   # Engine 6 — Oscillation

        # --- MA TRẬN BẺ CẦU ---
        self.last_raw_pred   = None
        self.last_raw_key    = None
        self.last_raw_bucket = None

        self.bait_matrix = {
            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False},
            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False}
        }
        self.bucket_streaks = {
            k: {b: {'loss': 0, 'win': 0} for b in [50, 60, 70, 80, 90, 100]}
            for k in self.bait_matrix
        }

        # --- WATCHDOG: Phát hiện API bị treo ---
        self.last_data_time = time.time()
        self.api_fail_count = 0
        self._watchdog_started = False
        self._start_watchdog()

    # ==========================================
    # 🐕 WATCHDOG — Phát hiện API đứng im
    # ==========================================
    def _start_watchdog(self):
        """
        Thread chạy nền, kiểm tra mỗi 60s.
        Nếu > 10 phút không có phiên mới:
          - Log cảnh báo rõ ràng
          - Reset last_session_id để buộc xử lý lại khi API sống lại
        Nếu > 5 phút:
          - Log cảnh báo nhẹ
        """
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
                        print(f"\n🚨 [WATCHDOG] ⚠️ {mins} PHÚT KHÔNG CÓ DỮ LIỆU MỚI!")
                        print("🔄 [WATCHDOG] Reset session_id để xử lý lại khi API sống...")
                        self.last_session_id = None  # Buộc xử lý lại ngay khi API phục hồi
                        self.last_data_time  = time.time()  # Tránh spam reset
                    elif elapsed > 300:
                        print(f"⚠️ [WATCHDOG] {mins} phút chưa có phiên mới — kiểm tra API/mạng.")

                except Exception as e:
                    print(f"⚠️ [WATCHDOG] Lỗi nội bộ: {e}")

        t = threading.Thread(target=_watch, daemon=True)
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
    # ⚙️ OPTUNA — Tối ưu hóa trọng số Bayesian
    # ==========================================
    def run_optuna_tuning(self, data: list):
        if len(data) < 30:
            return

        print("\n🔄 [OPTUNA] Tối ưu trọng số Bayesian 6 engine...")

        def objective(trial):
            w_markov = trial.suggest_float('w_markov', 0.5, 6.0)
            w_ngram  = trial.suggest_float('w_ngram',  0.5, 6.0)
            w_streak = trial.suggest_float('w_streak', 0.1, 4.0)
            w_ema    = trial.suggest_float('w_ema',    0.1, 3.0)
            w_dice   = trial.suggest_float('w_dice',   0.0, 1.5)
            w_osc    = trial.suggest_float('w_osc',    0.1, 3.0)

            test_len = min(30, len(data) - REQUIRED_LEN)
            correct  = 0

            for i in range(len(data) - test_len, len(data)):
                past = data[:i]
                if len(past) < REQUIRED_LEN:
                    continue

                seq       = ["T" if x['tong'] > 10 else "X" for x in past[-250:]]
                tong_list = [x['tong'] for x in past[-50:]]
                entropy   = shannon_entropy(seq)

                e_probs = [
                    engine_markov_chain(seq),
                    engine_ngram_pattern(seq)[0],
                    engine_streak_analysis(seq),
                    engine_ema_trend(seq),
                    engine_dice_regression(tong_list),
                    engine_oscillation(seq),
                ]
                weights = [w_markov, w_ngram, w_streak, w_ema, w_dice, w_osc]

                p_tai  = bayesian_combine(e_probs, weights, entropy)
                pred   = "TÀI" if p_tai >= 0.5 else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1

            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=60)   # 60 trials để tìm được tham số tốt hơn

        best           = study.best_params
        self.w_markov  = round(best['w_markov'], 3)
        self.w_ngram   = round(best['w_ngram'],  3)
        self.w_streak  = round(best['w_streak'], 3)
        self.w_ema     = round(best['w_ema'],    3)
        self.w_dice    = round(best['w_dice'],   3)
        self.w_osc     = round(best['w_osc'],    3)

        print(
            f"✅ [OPTUNA] Xong! "
            f"Markov={self.w_markov} | Ngram={self.w_ngram} | "
            f"Streak={self.w_streak} | EMA={self.w_ema} | "
            f"Dice={self.w_dice} | Osc={self.w_osc}\n"
        )

    # ==========================================
    # 🧮 PHÂN TÍCH & DỰ ĐOÁN
    # ==========================================
    def analyze_next_round(self, next_session_id: int):
        data = self.load_data()

        print(f"\n{'='*95}")
        print(f"🎯 PHÂN TÍCH PHIÊN {next_session_id}")
        print(f"{'='*95}")

        if len(data) < REQUIRED_LEN:
            msg = f"Thu thập dữ liệu: {len(data)}/{REQUIRED_LEN} ván..."
            print(f"⚠️ {msg}")
            self.sync_to_dashboard(next_session_id, "WAIT", msg)
            return

        # Chuỗi TX và danh sách tổng
        seq       = ["T" if x['tong'] > 10 else "X" for x in data[-250:]]
        tong_list = [x['tong'] for x in data[-60:]]

        # ─── TÍNH ENTROPY ───
        entropy = shannon_entropy(seq, window=30)
        if entropy > 0.90:
            entropy_label = "🔴 CAO — chuỗi ngẫu nhiên mạnh"
        elif entropy > 0.70:
            entropy_label = "🟡 TRUNG BÌNH — ít pattern"
        else:
            entropy_label = "🟢 THẤP — có pattern rõ ràng"

        # ─── CHẠY 6 ENGINE ───
        e1 = engine_markov_chain(seq)
        e2, e2_conf = engine_ngram_pattern(seq)
        e3 = engine_streak_analysis(seq)
        e4 = engine_ema_trend(seq)
        e5 = engine_dice_regression(tong_list)
        e6 = engine_oscillation(seq)

        engine_probs = [e1, e2, e3, e4, e5, e6]
        weights_list = [self.w_markov, self.w_ngram, self.w_streak, self.w_ema, self.w_dice, self.w_osc]

        # ─── KẾT HỢP BAYESIAN ───
        p_tai  = bayesian_combine(engine_probs, weights_list, entropy)
        p_xiu  = 1.0 - p_tai

        # ─── CHỐT GỐC ───
        chot_goc     = "TÀI" if p_tai >= 0.5 else "XỈU"
        conf_percent = round(max(p_tai, p_xiu) * 100.0, 1)
        matrix_key   = chot_goc
        current_bucket = self.get_confidence_bucket(conf_percent)

        # ─── LOG ───
        current_wr = (self.total_won / self.total_played * 100) if self.total_played > 0 else 50.0

        print(f"")
        print(f"📊 [ENTROPY] {entropy:.4f}  →  {entropy_label}")
        print(f"   (Scale trọng số: {max(0.3, 1.0 - entropy * 0.7):.2f})")
        print(f"")
        print(f"📘 [6 ENGINE — P(TÀI) | P(XỈU)]")
        print(f"   E1 Markov Chain (bậc 1-5)  : {e1*100:5.1f}% | {(1-e1)*100:5.1f}%  [w={self.w_markov}]")
        print(f"   E2 N-gram Pattern (3-7 kỳ) : {e2*100:5.1f}% | {(1-e2)*100:5.1f}%  [w={self.w_ngram}] conf={e2_conf:.2f}")
        print(f"   E3 Streak Analysis (thực tế): {e3*100:5.1f}% | {(1-e3)*100:5.1f}%  [w={self.w_streak}]")
        print(f"   E4 EMA Xu Hướng (α=0.25)   : {e4*100:5.1f}% | {(1-e4)*100:5.1f}%  [w={self.w_ema}]")
        print(f"   E5 Dice Regression (mean)   : {e5*100:5.1f}% | {(1-e5)*100:5.1f}%  [w={self.w_dice}]")
        print(f"   E6 Oscillation (cầu rung)   : {e6*100:5.1f}% | {(1-e6)*100:5.1f}%  [w={self.w_osc}]")
        print(f"")
        print(f"   ─── KẾT HỢP BAYESIAN LOG-ODDS ───")
        print(f"   => P(TÀI) = {p_tai*100:.2f}%  |  P(XỈU) = {p_xiu*100:.2f}%")
        print(f"   => CHỐT GỐC : {chot_goc} ({conf_percent}%)  [Bucket {current_bucket}%]")

        # ─── MA TRẬN BẺ CẦU ───
        nguong   = 4 if current_wr >= 55 else 3
        note     = ""
        chot_cuoi = chot_goc

        if self.bait_matrix[matrix_key][current_bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note      = f"⚠️ {matrix_key} {current_bucket}% đang lừa → ÉP BẺ SANG {chot_cuoi}"
        else:
            note = "Vào theo Bayesian đa engine"

        # Ghi nhớ cho vòng kế tiếp
        self.last_raw_pred        = chot_goc
        self.last_raw_key         = matrix_key
        self.last_raw_bucket      = current_bucket
        self.last_final_pred      = chot_cuoi
        self.history_predictions[str(next_session_id)] = chot_cuoi
        self.predicted_session_id = next_session_id

        wr_str = f" [WR: {self.total_won}/{self.total_played} = {current_wr:.1f}%]" if self.total_played > 0 else ""
        print(f"{'─'*95}")
        print(f"🔥 LỆNH CHỐT CUỐI : VÀO {chot_cuoi}  ←  {note}{wr_str}")

        detail = (
            f"Bayesian {chot_goc}({conf_percent:.1f}%) "
            f"H={entropy:.2f} → {note}"
        )
        self.sync_to_dashboard(next_session_id, chot_cuoi, detail)
        print(f"{'='*95}\n")

    # ==========================================
    # 📥 NẠP DỮ LIỆU MỚI + CHẤM ĐIỂM
    # ==========================================
    def inject_new_data(self, phien: int, dice: list, tong: int):
        actual_full           = "TÀI" if tong > 10 else "XỈU"
        self.last_data_time   = time.time()   # Cập nhật watchdog timestamp

        data = self.load_data()
        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': actual_full})
        self.save_data(data)

        # ─── CHẤM ĐIỂM NẾU ĐÚNG PHIÊN ───
        if self.last_final_pred is not None and self.predicted_session_id == phien:
            self.total_played += 1
            self.tune_counter += 1
            wr_now = (self.total_won / self.total_played) * 100

            if self.last_final_pred == actual_full:
                self.total_won += 1
                wr_now = (self.total_won / self.total_played) * 100
                print(f"💰 Ván {phien} HÚP {actual_full}!  WR: {self.total_won}/{self.total_played} ({wr_now:.1f}%)")
            else:
                print(f"💀 Ván {phien} GÃY!  WR: {self.total_won}/{self.total_played} ({wr_now:.1f}%)")

            # Optuna mỗi 15 ván (chạy background thread để không block)
            if self.tune_counter >= 15:
                self.tune_counter = 0
                snapshot = list(data)  # Copy để tránh race condition
                threading.Thread(
                    target=self.run_optuna_tuning,
                    args=(snapshot,),
                    daemon=True,
                    name="OptunaThread"
                ).start()

            # ─── MA TRẬN BẺ CẦU CẬP NHẬT ───
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
                            print(f"🚨 [MA TRẬN] {mk} {bk}% GÃY {nguong} TAY! BẬT BẺ CẦU.")
                    else:
                        streak['loss'] = 0
                else:
                    if raw_correct:
                        streak['win']  += 1
                        streak['loss']  = 0
                        if streak['win'] >= 2:
                            self.bait_matrix[mk][bk] = False
                            streak['win']            = 0
                            print(f"✅ [MA TRẬN] {mk} {bk}% ổn định 2 tay! TẮT BẺ CẦU.")
                    else:
                        streak['win'] = 0

        elif self.predicted_session_id is not None and self.predicted_session_id != phien:
            print(
                f"⚠️ [LỆCH PHIÊN] Dự đoán cho phiên {self.predicted_session_id} "
                f"nhưng API trả phiên {phien} — bỏ qua chấm điểm."
            )

        return len(data)

    # ==========================================
    # 🔄 VÒNG LẶP CHÍNH — Xử lý lỗi phân loại + Exponential Backoff
    # ==========================================
    def run(self):
        print("🚀 Khởi động SUNWIN AI v7 — BAYESIAN 6-ENGINE + WATCHDOG...")
        retry_delay = 2.0   # giây

        while True:
            try:
                res = requests.get(API_ENDPOINT, headers=HEADERS, timeout=10)
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

                # Thành công → reset delay về 2s
                retry_delay          = 2.0
                self.api_fail_count  = 0

            # ─── XỬ LÝ LỖI PHÂN LOẠI — Không dùng except: pass nữa ───
            except requests.exceptions.Timeout:
                self.api_fail_count += 1
                print(f"⏰ [API] Timeout #{self.api_fail_count}. Retry sau {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 60.0)   # Tối đa 60s

            except requests.exceptions.ConnectionError as e:
                self.api_fail_count += 1
                print(f"🔌 [API] Mất kết nối #{self.api_fail_count}: {e}. Retry sau {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 60.0)

            except requests.exceptions.HTTPError as e:
                self.api_fail_count += 1
                status = e.response.status_code if e.response else "?"
                print(f"❌ [API] HTTP {status} #{self.api_fail_count}. Retry sau {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 120.0)  # 4xx/5xx → backoff mạnh hơn

            except requests.exceptions.JSONDecodeError:
                self.api_fail_count += 1
                print(f"⚠️ [API] Phản hồi không phải JSON. Retry sau {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 30.0)

            except KeyError as e:
                # API trả JSON nhưng thiếu field
                print(f"⚠️ [API] Thiếu field {e} trong JSON. Tiếp tục...")
                time.sleep(2.0)

            except Exception as e:
                self.api_fail_count += 1
                print(f"❌ [LỖI] {type(e).__name__}: {e}. Retry sau {retry_delay:.1f}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 30.0)

            time.sleep(2)


# ==========================================
# 🚀 ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(
        target=lambda: SunwinLogic_v7().run(),
        daemon=True,
        name="MainLogicThread"
    ).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

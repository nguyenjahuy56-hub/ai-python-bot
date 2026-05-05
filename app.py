import time
import requests
import json
import os
import sys
import threading
import optuna
from pymongo import MongoClient
from flask import Flask

# Tắt log rác của Optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️ CONFIG HỆ THỐNG & THÔNG TIN XÁC THỰC
# ==========================================
API_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"

# LINK MONGODB CỦA BRO
MONGO_URI = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"

# DỮ LIỆU XÁC THỰC (Đã được cập nhật theo yêu cầu)
USER_AUTH_DATA = {
    "accessToken": "467f7b98eb72487ca19273002cc07bf4",
    "refreshToken": "a34c7dff4fd94f0fb8889fc8744be629.0fc0ea6755624a82a1597925c0efb43d",
    "wsToken": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJnZW5kZXIiOjAsImNhblZpZXdTdGF0IjpmYWxzZSwiZGlzcGxheU5hbWUiOiJzb25ndmVkZW0yMCIsImJvdCI6MCwiaXNNZXJjaGFudCI6ZmFsc2UsInZlcmlmaWVkQmFua0FjY291bnQiOnRydWUsInBsYXlFdmVudExvYmJ5IjpmYWxzZSwiY3VzdG9tZXJJZCI6MjM5OTUzMjE1LCJhZmZJZCI6ImRlZmF1bHQiLCJiYW5uZWQiOmZhbHNlLCJicmFuZCI6InN1bi53aW4iLCJlbWFpbCI6IiIsInRpbWVzdGFtcCI6MTc3Nzk1NTYwMzA0NywibG9ja0dhbWVzIjpbXSwiYW1vdW50IjowLCJsb2NrQ2hhdCI6ZmFsc2UsInBob25lVmVyaWZpZWQiOnRydWUsImlwQWRkcmVzcyI6IjExMy4xNzUuMTM3LjE4MCIsIm11dGUiOmZhbHNlLCJhdmF0YXIiOiJodHRwczovL2ltYWdlcy5zd2luc2hvcC5uZXQvaW1hZ2VzL2F2YXRhci9hdmF0YXJfMTAucG5nIiwicGxhdGZvcm1JZCI6MiwidXNlcklkIjoiMDAzNzQwNjgtOGJmYi00OTU2LTliMTItMjg5M2MzMTA3MTYwIiwiZW1haWxWZXJpZmllZCI6bnVsbCwicmVnVGltZSI6MTc0NTU5MjY1NTgwNywicGhvbmUiOiI4NDMyOTY4OTk3MSIsImRlcG9zaXQiOnRydWUsInVzZXJuYW1lIjoiU0Nfc29uZ3ZlZGVtMTAifQ.O6qjN0boaqSDJVzjvzc4ZQfdylxzlhU76qCFwUprY9w",
    "signature": "0AC751198C16DC4545E67C4F36CEEF54A4EE984436A11FB53F182E44F7BC61803BF17F00E749E0D01CEB679BDE72B85071861418BD938E783A3645E3EE45069EA849692BDF02900FBA0DB2F127B0BE72EAE40D642765DD7C04965B98562DDFE450255C9CBF8DF0EB02C2D999A25DD46CBAD32D1CA5470759741E955DDBCDE5BE",
    "userId": "00374068-8bfb-4956-9b12-2893c3107160",
    "username": "SC_songvedem10"
}

# Headers cho các requests nếu cần đính kèm Token
HEADERS = {
    "Authorization": f"Bearer {USER_AUTH_DATA['accessToken']}",
    "wsToken": USER_AUTH_DATA['wsToken'],
    "signature": USER_AUTH_DATA['signature'],
    "Content-Type": "application/json"
}

HISTORY_MAX = 200          
REQUIRED_LEN = 13  # Bỏ 13 phiên đầu để lấy đủ chuỗi TX

# 🛠️ KẾT NỐI MONGODB THAY CHO FIREBASE
try:
    client = MongoClient(MONGO_URI)
    db = client['sunwin_database']
    collection = db['history']
    client.admin.command('ping')
    print("✅ KẾT NỐI MONGODB THÀNH CÔNG! Đã khai tử Firebase lỏ.")
except Exception as e:
    print(f"❌ LỖI KẾT NỐI MONGODB: {e}")

app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "🔥 AI Server v6 FINAL - MONGODB STABLE + FULL LOGIC..."

# ==========================================
# 🧠 LÕI 1: TRỌNG SỐ CHUỖI 13 VÁN (TỪ CŨ TỚI MỚI)
# ==========================================
def phan_tich_chuoi_weighted(chuoi):
    weights = [1.5**i for i in range(len(chuoi))]
    tong_weight = sum(weights)
    tai = sum(w for x, w in zip(chuoi, weights) if x == "T")
    xiu = sum(w for x, w in zip(chuoi, weights) if x == "X")
    return round(tai / tong_weight * 100, 1), round(xiu / tong_weight * 100, 1)

def du_doan_tu_chuoi(chuoi_50):
    chuoi = chuoi_50[-13:] if len(chuoi_50) >= 13 else chuoi_50
    perc_tai, perc_xiu = phan_tich_chuoi_weighted(chuoi)
    return "XONG", perc_tai, perc_xiu

# ==========================================
# 🧠 LỌC BỆT DÀI (PRE-PROCESSING)
# ==========================================
def loai_bo_bet_dai(chuoi_kq, max_streak=5):
    if not chuoi_kq: return []
    
    cleaned = []
    current_char = chuoi_kq[0]
    count = 1
    
    cleaned.append(current_char)
    
    for i in range(1, len(chuoi_kq)):
        if chuoi_kq[i] == current_char:
            count += 1
        else:
            current_char = chuoi_kq[i]
            count = 1
            
        if count <= max_streak:
            cleaned.append(chuoi_kq[i])
            
    return cleaned

# ==========================================
# 🧠 LÕI 2A: MẪU CẦU XÚC XẮC 130 VÁN (MẪU 4-5 ĐIỂM)
# ==========================================
def predict_maucau_diem(list_tong_130, w_m5, w_m4):
    if len(list_tong_130) < 5:
        return 0, 0, "[]"

    last_5 = list_tong_130[-5:]
    last_4 = list_tong_130[-4:]

    t5, x5, t4, x4 = 0, 0, 0, 0
    # Quét Mẫu 5
    for i in range(len(list_tong_130) - 4):
        if list_tong_130[i:i+4] == last_5[:-1]:
            if list_tong_130[i+4] > 10: t5 += 1
            else: x5 += 1

    # Quét Mẫu 4
    for i in range(len(list_tong_130) - 3):
        if list_tong_130[i:i+3] == last_4[:-1]:
            if list_tong_130[i+3] > 10: t4 += 1
            else: x4 += 1

    diem_tai = (t5 * w_m5) + (t4 * w_m4)
    diem_xiu = (x5 * w_m5) + (x4 * w_m4)
    mc_log = f"[{'-'.join(map(str, last_4))}]"
    
    return diem_tai, diem_xiu, mc_log

# ==========================================
# 🧠 LÕI 2B: MẪU CẦU KÝ TỰ T/X (5-7 KÝ TỰ TRONG 80 VÁN)
# ==========================================
def predict_maucau_tx_diem(chuoi_80_kq, w_tx):
    # LỌC BỆT DÀI TRƯỚC KHI QUÉT MẪU
    chuoi_sach = loai_bo_bet_dai(chuoi_80_kq, max_streak=5)
    
    if len(chuoi_sach) < 8: 
        return 0.0, 0.0, "[]"

    t_pts, x_pts = 0.0, 0.0
    # Xếp từ dài nhất (7) xuống ngắn nhất (5)
    patterns = [{'len': 7, 'mult': 4.0}, {'len': 6, 'mult': 3.0}, {'len': 5, 'mult': 2.0}]
    mc_tx_log = ""
    
    for p in patterns:
        p_len, mult = p['len'], p['mult']
        if len(chuoi_sach) <= p_len: continue
        
        target = chuoi_sach[-p_len:]
        t_count, x_count = 0, 0
        
        # Quét lại trong 80 ván quá khứ
        for i in range(len(chuoi_sach) - p_len):
            if chuoi_sach[i:i+p_len] == target:
                next_val = chuoi_sach[i+p_len]
                if next_val == "T": t_count += 1
                else: x_count += 1
        
        # CHỈ ƯU TIÊN MẪU DÀI NHẤT KHỚP ĐƯỢC
        if t_count > 0 or x_count > 0:
            t_pts += t_count * mult * w_tx
            x_pts += x_count * mult * w_tx
            mc_tx_log = f"[{''.join(target)}]" 
            break # Ngắt luôn, không quét các mẫu ngắn hơn nữa
        
    return round(t_pts, 1), round(x_pts, 1), mc_tx_log or "[]"

# ==========================================
# 🧠 LÕI 3: LOGIC XU HƯỚNG (TREND)
# ==========================================
def predict_trend_logic(chuoi_50_kq, w_trend):
    last_5 = chuoi_50_kq[-5:] if len(chuoi_50_kq) >= 5 else chuoi_50_kq
    t5 = sum(1 for x in last_5 if x == "T")
    x5 = sum(1 for x in last_5 if x == "X")
    trend_score = (t5 - x5) * w_trend * 0.6 
    return trend_score

# ==========================================
# 🧠 LÕI 4: LOGIC BẺ BỆT (SAU 3 TAY BỆT)
# ==========================================
def predict_be_bet_logic(chuoi_50_kq, w_be_bet):
    if len(chuoi_50_kq) < 3: return 0
    last_3 = chuoi_50_kq[-3:]
    # Nếu 3 ván gần nhất là T-T-T -> Ưu tiên bẻ sang XỈU
    if all(x == 'T' for x in last_3): return -w_be_bet
    # Nếu 3 ván gần nhất là X-X-X -> Ưu tiên bẻ sang TÀI
    if all(x == 'X' for x in last_3): return w_be_bet
    return 0

# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH
# ==========================================
class SunwinLogic_Merged:
    def __init__(self):
        self.last_session_id = None
        
        self.total_played = 0
        self.total_won = 0
        self.last_final_pred = None 
        self.predicted_session_id = None # BỘ NHỚ LƯU PHIÊN DỰ ĐOÁN (Chống lệch)
        self.history_predictions = {}
        
        # --- THAM SỐ TỐI ƯU CỦA OPTUNA ---
        self.w_chuoi = 1.0  
        self.w_m5 = 1.0     
        self.w_m4 = 0.5     
        self.w_tx = 1.0     
        self.w_trend = 1.0  
        self.w_be_bet = 1.0 
        
        self.tune_counter = 0
        
        # --- HỆ THỐNG BAIT ---
        self.last_raw_pred = None     
        self.last_raw_key = None      
        self.last_raw_bucket = None   
        
        self.bait_matrix = {
            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False},
            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False}
        }
        self.bucket_streaks = {k: {b: {'loss': 0, 'win': 0} for b in [50, 60, 70, 80, 90, 100]} for k in self.bait_matrix.keys()}

    def load_data(self):
        try:
            doc = collection.find_one({'config': 'history_array'})
            return doc['data'] if doc and 'data' in doc else []
        except Exception as e:
            print(f"❌ LỖI ĐỌC MONGODB: {e}")
            return []

    def save_data(self, data):
        try:
            collection.update_one({'config': 'history_array'}, {'$set': {'data': data[-HISTORY_MAX:]}}, upsert=True)
        except Exception as e:
            print(f"❌ LỖI LƯU MONGODB: {e}")

    def get_confidence_bucket(self, percent):
        if percent >= 100: return 100
        elif percent >= 90: return 90
        elif percent >= 80: return 80
        elif percent >= 70: return 70
        elif percent >= 60: return 60
        else: return 50

    def sync_to_dashboard(self, next_phien, pred, detail):
        try:
            wr = (self.total_won / self.total_played * 100) if self.total_played > 0 else 0
            full_data = self.load_data()
            history_list = []
            for item in full_data[-20:]:
                phien = item['phien']
                actual_res = "TÀI" if item['tong'] > 10 else "XỈU"
                bot_pred = self.history_predictions.get(str(phien), "--")
                history_list.append({
                    "phien": phien, "pred": bot_pred,
                    "actual": actual_res, "win": (bot_pred == actual_res) if bot_pred != "--" else None
                })
            payload = {
                "result": pred, "detail": detail,
                "win_rate": round(wr, 1), "total_played": self.total_played,
                "history": history_list[::-1]
            }
            # Gửi payload kèm theo headers chứa token (nếu backend yêu cầu)
            requests.post(SYNC_ENDPOINT, json=payload, headers=HEADERS, timeout=5)
        except: pass

    # ==========================================
    # ⚙️ OPTUNA: TỐI ƯU HÓA
    # ==========================================
    def run_optuna_tuning(self, data):
        if len(data) < 30: return 
        
        print("\n🔄 [OPTUNA] Đang dò tìm trọng số mịn (Float) để chống nhiễu...")
        
        def objective(trial):
            w_chuoi = trial.suggest_float('w_chuoi', 0.5, 3.0)
            w_m5 = trial.suggest_float('w_m5', 0.1, 2.0)
            w_m4 = trial.suggest_float('w_m4', 0.1, 1.0)
            w_tx = trial.suggest_float('w_tx', 0.1, 2.0)
            w_trend = trial.suggest_float('w_trend', 0.1, 2.0) 
            w_be_bet = trial.suggest_float('w_be_bet', 0.1, 5.0) 
            
            test_len = min(20, len(data) - 13)
            correct = 0
            
            for i in range(len(data) - test_len, len(data)):
                past_data = data[:i]
                
                # 1. Chuỗi TX
                chuoi_50_kq = ["T" if x['tong'] > 10 else "X" for x in past_data[-50:]]
                _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50_kq)
                
                # 2. Base Hợp nhất (Modulo đã bị khai tử)
                avg_tai = chuoi_tai
                avg_xiu = chuoi_xiu
                
                # 3. Tính điểm Mẫu cầu 130 ván xúc xắc
                list_tong_130 = [x['tong'] for x in past_data[-130:]]
                chuoi_80_kq = ["T" if x['tong'] > 10 else "X" for x in past_data[-80:]]
                
                mc_xx_tai, mc_xx_xiu, _ = predict_maucau_diem(list_tong_130, w_m5, w_m4)
                mc_tx_tai, mc_tx_xiu, _ = predict_maucau_tx_diem(chuoi_80_kq, w_tx)

                # 4. Tính điểm Xu hướng
                trend_val = predict_trend_logic(chuoi_50_kq, w_trend)
                
                # 5. Tính điểm Bẻ bệt
                be_bet_val = predict_be_bet_logic(chuoi_50_kq, w_be_bet)
                
                # 6. Cap limit điểm cộng
                bonus_tai = min(20.0, mc_xx_tai + mc_tx_tai + (trend_val if trend_val > 0 else 0) + (be_bet_val if be_bet_val > 0 else 0)) 
                bonus_xiu = min(20.0, mc_xx_xiu + mc_tx_xiu + (abs(trend_val) if trend_val < 0 else 0) + (abs(be_bet_val) if be_bet_val < 0 else 0)) 
                
                pred = "TÀI" if (avg_tai + bonus_tai) > (avg_xiu + bonus_xiu) else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1
            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=35)
        
        self.w_chuoi = round(study.best_params['w_chuoi'], 2)
        self.w_m5 = round(study.best_params['w_m5'], 2)
        self.w_m4 = round(study.best_params['w_m4'], 2)
        self.w_tx = round(study.best_params['w_tx'], 2)
        self.w_trend = round(study.best_params['w_trend'], 2) 
        self.w_be_bet = round(study.best_params['w_be_bet'], 2) 
        
        print(f"✅ [OPTUNA] Xong! W_Chuoi:{self.w_chuoi} | Dice130(5/4):{self.w_m5}/{self.w_m4} | M_TX:{self.w_tx} | Trend:{self.w_trend} | BeBet:{self.w_be_bet}\n")

    def inject_new_data(self, phien, dice, tong):
        actual_full = "TÀI" if tong > 10 else "XỈU"

        data = self.load_data()
        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': actual_full})
        self.save_data(data)
        
        # --- CHỈ ĐÁNH GIÁ THẮNG/THUA NẾU KHỚP ĐÚNG PHIÊN ĐÃ DỰ ĐOÁN ---
        if self.last_final_pred is not None and self.predicted_session_id == phien:
            self.total_played += 1
            self.tune_counter += 1
            
            if self.last_final_pred == actual_full:
                self.total_won += 1
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💰 Ván {phien} HÚP {actual_full}! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
            else:
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💀 Ván {phien} GÃY! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
                
            if self.tune_counter >= 20:
                self.tune_counter = 0
                self.run_optuna_tuning(data)
        
            # --- MA TRẬN BẺ CẦU LINH HOẠT THEO WINRATE ---
            current_wr = (self.total_won / self.total_played * 100) if self.total_played > 0 else 50
            
            # Tính ngưỡng bẻ cầu động (Nâng nhẹ đáy lên 3 để đỡ bị bẻ quá nhạy khi WR thấp)
            if current_wr >= 55:
                nguong_be_cau = 4
            else:
                nguong_be_cau = 3

            if self.last_raw_key is not None and self.last_raw_bucket is not None:
                raw_was_correct = (self.last_raw_pred == actual_full) 
                matrix_key = self.last_raw_key
                bucket = self.last_raw_bucket
                streak = self.bucket_streaks[matrix_key][bucket]
                
                if not self.bait_matrix[matrix_key][bucket]:
                    if not raw_was_correct:
                        streak['loss'] += 1
                        streak['win'] = 0
                        if streak['loss'] >= nguong_be_cau:
                            self.bait_matrix[matrix_key][bucket] = True
                            streak['loss'] = 0
                            print(f"🚨 [MA TRẬN] {matrix_key} {bucket}% GÃY {nguong_be_cau} TAY (WR: {current_wr:.1f}%)! BẬT CHẾ ĐỘ BẺ CẦU.")
                    else: streak['loss'] = 0
                else:
                    if raw_was_correct:
                        streak['win'] += 1
                        streak['loss'] = 0
                        if streak['win'] >= 2: 
                            self.bait_matrix[matrix_key][bucket] = False
                            streak['win'] = 0
                            print(f"✅ [MA TRẬN] Cầu {matrix_key} {bucket}% chuẩn form 2 tay! TẮT BẺ CẦU.")
                    else: streak['win'] = 0
                    
        elif self.predicted_session_id is not None and self.predicted_session_id != phien:
            print(f"⚠️ [LỆCH PHIÊN] Bỏ qua chấm điểm! Tool dự đoán cho phiên {self.predicted_session_id} nhưng API trả kết quả phiên {phien}.")
            
        return len(data)

    def analyze_next_round(self, next_session_id):
        data = self.load_data()
        
        print(f"\n{'='*85}")
        print(f"🎯 PHÂN TÍCH PHIÊN {next_session_id}")
        print(f"{'='*85}")

        if len(data) < REQUIRED_LEN:
            print(f"⚠️ Đang thu thập dữ liệu chuỗi: {len(data)}/{REQUIRED_LEN} ván.")
            self.sync_to_dashboard(next_session_id, "WAIT", f"Đang nạp mồi: {len(data)}/{REQUIRED_LEN} ván")
            return

        # 1. Dữ liệu Trọng Số 13 Ván (Làm Base chính)
        chuoi_50_kq = ["T" if item['tong'] > 10 else "X" for item in data[-50:]]
        _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50_kq)

        # 2. % Base Hợp nhất
        chia_tai = chuoi_tai
        chia_xiu = chuoi_xiu

        # 3. Điểm Mẫu Cầu 130 ván xúc xắc & 80 ván TX
        list_tong_130 = [item['tong'] for item in data[-130:]]
        chuoi_80_kq = ["T" if item['tong'] > 10 else "X" for item in data[-80:]]
        
        mc_xx_tai, mc_xx_xiu, mc_xx_log = predict_maucau_diem(list_tong_130, self.w_m5, self.w_m4)
        mc_tx_tai, mc_tx_xiu, mc_tx_log = predict_maucau_tx_diem(chuoi_80_kq, self.w_tx)

        # 4. Điểm Xu hướng (Trend)
        trend_val = predict_trend_logic(chuoi_50_kq, self.w_trend)

        # 5. Điểm Bẻ bệt (Logic mới: Cộng tỉ lệ sau 3 tay bệt)
        be_bet_val = predict_be_bet_logic(chuoi_50_kq, self.w_be_bet)

        # BỘ LỌC NHIỄU (Cap limit max 20, tích hợp Trend & Bẻ bệt)
        bonus_tai = min(20.0, mc_xx_tai + mc_tx_tai + (trend_val if trend_val > 0 else 0) + (be_bet_val if be_bet_val > 0 else 0)) 
        bonus_xiu = min(20.0, mc_xx_xiu + mc_tx_xiu + (abs(trend_val) if trend_val < 0 else 0) + (abs(be_bet_val) if be_bet_val < 0 else 0)) 

        # Hợp nhất Toán học
        final_tai = chia_tai + bonus_tai
        final_xiu = chia_xiu + bonus_xiu

        # CHỐT GỐC
        if final_tai > final_xiu:
            chot_goc = "TÀI"
            conf_percent = min(100.0, round(final_tai, 1))
        else:
            chot_goc = "XỈU"
            conf_percent = min(100.0, round(final_xiu, 1))
            
        matrix_key = chot_goc
        current_bucket = self.get_confidence_bucket(conf_percent)

        # In Log
        print(f"📘 [LOGIC: HỢP NHẤT TRỌNG SỐ & MẪU KÉP (KHAI TỬ MODULO)]")
        print(f"   => Trọng số 13  : TÀI {chuoi_tai:.1f}% | XỈU {chuoi_xiu:.1f}%")
        print(f"   => Điểm Mẫu XX  : +{round(mc_xx_tai,1)} TÀI | +{round(mc_xx_xiu,1)} XỈU (Mẫu {mc_xx_log})")
        print(f"   => Điểm Mẫu TX  : +{mc_tx_tai} TÀI | +{mc_tx_xiu} XỈU (Mẫu {mc_tx_log})")
        print(f"   => Điểm XU HƯỚNG: {'+' if trend_val > 0 else ''}{round(trend_val, 1)} (Trend {abs(trend_val)})") 
        print(f"   => Điểm BẺ BỆT  : {'+' if be_bet_val > 0 else ''}{round(be_bet_val, 1)} (Sau 3 ván bệt)") 
        print(f"   => TỔNG KẾT     : Khớp logic {chot_goc} ({conf_percent}%)")
        print(f"   => Trạng thái   : [MỐC LƯU: {matrix_key} {current_bucket}%]")

        note = ""
        chot_cuoi = chot_goc
        
        # Ma trận Bẻ cầu
        if self.bait_matrix[matrix_key][current_bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note = f" (⚠️ {matrix_key} mốc {current_bucket}% đang lừa -> ÉP BẺ SANG {chot_cuoi})"
        else:
            note = f" (Vào theo phân tích hợp nhất đa tầng)"

        self.last_raw_pred = chot_goc
        self.last_raw_key = matrix_key
        self.last_raw_bucket = current_bucket
        self.last_final_pred = chot_cuoi
        self.history_predictions[str(next_session_id)] = chot_cuoi
        self.predicted_session_id = next_session_id # <--- GHI NHỚ LẠI PHIÊN MÌNH VỪA CHỐT
        
        print(f"{'-'*85}")
        wr_str = f" [WR Hiện tại: {(self.total_won/self.total_played)*100:.1f}%]" if self.total_played > 0 else ""
        print(f"🔥 LỆNH CHỐT CUỐI : VÀO {chot_cuoi} {note}{wr_str}")
        
        detail = f"{chot_goc} ({conf_percent:.1f}%) ➔ {note.replace('(', '').replace(')', '')}"
        self.sync_to_dashboard(next_session_id, chot_cuoi, detail)
        print(f"{'='*85}\n")

    def run(self):
        print("🚀 Khởi động TOOL v6 (MONGODB ACTIVE)...")
        while True:
            try:
                # Đính kèm HEADERS chứa thông tin User vào Requests để xác thực
                res = requests.get(API_ENDPOINT, headers=HEADERS, timeout=3)
                res.raise_for_status()
                api_data = res.json()
                
                if not api_data.get("Phien"):
                    time.sleep(2)
                    continue

                curr_session = int(api_data["Phien"])

                if curr_session != self.last_session_id:
                    self.last_session_id = curr_session
                    dice = [int(api_data["Xuc_xac_1"]), int(api_data["Xuc_xac_2"]), int(api_data["Xuc_xac_3"])]
                    tong = int(api_data["Tong"])
                    
                    tx_str = "TÀI" if tong > 10 else "XỈU"
                    print(f"\n✅ NẠP THÀNH CÔNG: PHIÊN {curr_session} | Điểm: {tong} ({tx_str})")
                    
                    self.inject_new_data(curr_session, dice, tong)
                    self.analyze_next_round(curr_session + 1)

            except Exception as e:
                pass
            time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=lambda: SunwinLogic_Merged().run(), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

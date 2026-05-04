import time
import requests
import json
import os
import sys
import threading
import hashlib
import optuna
from pymongo import MongoClient
from flask import Flask

# Tắt log rác của Optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️ CONFIG HỆ THỐNG
# ==========================================
API_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"

# LINK MONGODB CỦA BRO
MONGO_URI = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"

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
# 🧠 LÕI 1: MODULO 11 + HASH CONFIDENCE
# ==========================================
def get_confidence(v1, v2, v3):
    raw_string = f"{v1}-{v2}-{v3}"
    hash_hex = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()
    
    high_byte = 0
    low_byte = 0
    
    for i in range(0, 64, 2):
        byte_val = int(hash_hex[i:i+2], 16)
        if byte_val > 127: high_byte += 1
        else: low_byte += 1
            
    delta = abs(high_byte - low_byte)
    wr = 62 + (delta * 1.8)
    return min(round(wr, 1), 98.8)

def predict_tx(v1, v2, v3):
    s = (2 * v1) + (3 * v2) + (4 * v3)
    r = s % 11
    result = "XỈU" if r <= 5 else "TÀI"
    conf = get_confidence(v1, v2, v3)
    return result, conf

# ==========================================
# 🧠 LÕI 2: TRỌNG SỐ CHUỖI 13 VÁN (TỪ CŨ TỚI MỚI)
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
# 🧠 LÕI 3A: MẪU CẦU XÚC XẮC 100 VÁN (DẠNG + ĐIỂM)
# ==========================================
def predict_maucau_diem(list_tong_100, w_m4, w_m3):
    if len(list_tong_100) < 4:
        return 0, 0, "[]"

    last_3 = list_tong_100[-3:]
    last_2 = list_tong_100[-2:]

    t4, x4, t3, x3 = 0, 0, 0, 0
    # Quét Mẫu 4
    for i in range(len(list_tong_100) - 3):
        if list_tong_100[i:i+3] == last_3:
            if list_tong_100[i+3] > 10: t4 += 1
            else: x4 += 1

    # Quét Mẫu 3
    for i in range(len(list_tong_100) - 2):
        if list_tong_100[i:i+2] == last_2:
            if list_tong_100[i+2] > 10: t3 += 1
            else: x3 += 1

    diem_tai = (t4 * w_m4) + (t3 * w_m3)
    diem_xiu = (x4 * w_m4) + (x3 * w_m3)
    mc_log = f"[{'-'.join(map(str, last_3))}]"
    
    return diem_tai, diem_xiu, mc_log

# ==========================================
# 🧠 LÕI 3B: MẪU CẦU KÝ TỰ T/X (4-6 KÝ TỰ TRONG 50 VÁN)
# ==========================================
def predict_maucau_tx_diem(chuoi_50_kq, w_tx):
    # LỌC BỆT DÀI TRƯỚC KHI QUÉT MẪU
    chuoi_sach = loai_bo_bet_dai(chuoi_50_kq, max_streak=5)
    
    if len(chuoi_sach) < 7: 
        return 0.0, 0.0, "[]"

    t_pts, x_pts = 0.0, 0.0
    patterns = [{'len': 6, 'mult': 3.0}, {'len': 5, 'mult': 2.0}, {'len': 4, 'mult': 1.0}]
    mc_tx_log = ""
    
    for p in patterns:
        p_len, mult = p['len'], p['mult']
        if len(chuoi_sach) <= p_len: continue
        
        target = chuoi_sach[-p_len:]
        t_count, x_count = 0, 0
        
        # Quét lại trong 50 ván quá khứ
        for i in range(len(chuoi_sach) - p_len):
            if chuoi_sach[i:i+p_len] == target:
                next_val = chuoi_sach[i+p_len]
                if next_val == "T": t_count += 1
                else: x_count += 1
        
        if t_count > 0 or x_count > 0:
            t_pts += t_count * mult * w_tx
            x_pts += x_count * mult * w_tx
            if not mc_tx_log: mc_tx_log = f"[{''.join(target)}]" 
        
    return round(t_pts, 1), round(x_pts, 1), mc_tx_log or "[]"

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
        self.w_mod = 1.0    
        self.w_chuoi = 1.0  
        self.w_m4 = 1.0     
        self.w_m3 = 0.5     
        self.w_tx = 1.0     
        
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
            requests.post(SYNC_ENDPOINT, json=payload, timeout=5)
        except: pass

    # ==========================================
    # ⚙️ OPTUNA: TỐI ƯU HÓA
    # ==========================================
    def run_optuna_tuning(self, data):
        if len(data) < 30: return 
        
        print("\n🔄 [OPTUNA] Đang dò tìm trọng số mịn (Float) để chống nhiễu...")
        
        def objective(trial):
            w_mod = trial.suggest_float('w_mod', 0.5, 3.0)
            w_chuoi = trial.suggest_float('w_chuoi', 0.5, 3.0)
            w_m4 = trial.suggest_float('w_m4', 0.1, 2.0)
            w_m3 = trial.suggest_float('w_m3', 0.1, 1.0)
            w_tx = trial.suggest_float('w_tx', 0.1, 2.0)
            
            test_len = min(20, len(data) - 13)
            correct = 0
            
            for i in range(len(data) - test_len, len(data)):
                past_data = data[:i]
                
                # 1. Modulo
                v1, v2, v3 = past_data[-3]['tong'], past_data[-2]['tong'], past_data[-1]['tong']
                mod_pred, mod_conf = predict_tx(v1, v2, v3)
                mod_tai = mod_conf if mod_pred == "TÀI" else (100 - mod_conf)
                mod_xiu = mod_conf if mod_pred == "XỈU" else (100 - mod_conf)
                
                # 2. Chuỗi TX
                chuoi_50_kq = ["T" if x['tong'] > 10 else "X" for x in past_data[-50:]]
                _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50_kq)
                
                # 3. Base Hợp nhất
                avg_tai = ((mod_tai * w_mod) + (chuoi_tai * w_chuoi)) / (w_mod + w_chuoi)
                avg_xiu = ((mod_xiu * w_mod) + (chuoi_xiu * w_chuoi)) / (w_mod + w_chuoi)
                
                # 4. Tính điểm Mẫu cầu
                list_tong_100 = [x['tong'] for x in past_data[-100:]]
                mc_xx_tai, mc_xx_xiu, _ = predict_maucau_diem(list_tong_100, w_m4, w_m3)
                mc_tx_tai, mc_tx_xiu, _ = predict_maucau_tx_diem(chuoi_50_kq, w_tx)
                
                # 5. Cap limit điểm cộng
                bonus_tai = min(20.0, mc_xx_tai + mc_tx_tai)
                bonus_xiu = min(20.0, mc_xx_xiu + mc_tx_xiu)
                
                pred = "TÀI" if (avg_tai + bonus_tai) > (avg_xiu + bonus_xiu) else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1
            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=35)
        
        self.w_mod = round(study.best_params['w_mod'], 2)
        self.w_chuoi = round(study.best_params['w_chuoi'], 2)
        self.w_m4 = round(study.best_params['w_m4'], 2)
        self.w_m3 = round(study.best_params['w_m3'], 2)
        self.w_tx = round(study.best_params['w_tx'], 2)
        
        print(f"✅ [OPTUNA] Xong! W_Mod:{self.w_mod} | W_Chuoi:{self.w_chuoi} | M4:{self.w_m4} | M3:{self.w_m3} | M_TX:{self.w_tx}\n")

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
                        if streak['win'] >= nguong_be_cau:
                            self.bait_matrix[matrix_key][bucket] = False
                            streak['win'] = 0
                            print(f"✅ [MA TRẬN] Cầu {matrix_key} {bucket}% chuẩn form {nguong_be_cau} tay! TẮT BẺ CẦU.")
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

        # 1. Dữ liệu Modulo
        recent_3 = data[-3:]
        v1, v2, v3 = recent_3[0]['tong'], recent_3[1]['tong'], recent_3[2]['tong']
        mod_pred, mod_conf = predict_tx(v1, v2, v3)
        mod_tai = mod_conf if mod_pred == "TÀI" else (100 - mod_conf)
        mod_xiu = mod_conf if mod_pred == "XỈU" else (100 - mod_conf)

        # 2. Dữ liệu Trọng Số 13 Ván & Mẫu Cầu TX
        chuoi_50_kq = ["T" if item['tong'] > 10 else "X" for item in data[-50:]]
        _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50_kq)

        # 3. Tính toán Chia 2 Tỉ lệ Base
        chia_tai = ((mod_tai * self.w_mod) + (chuoi_tai * self.w_chuoi)) / (self.w_mod + self.w_chuoi)
        chia_xiu = ((mod_xiu * self.w_mod) + (chuoi_xiu * self.w_chuoi)) / (self.w_mod + self.w_chuoi)

        # 4. Điểm Mẫu Cầu
        list_tong_100 = [item['tong'] for item in data[-100:]]
        mc_xx_tai, mc_xx_xiu, mc_xx_log = predict_maucau_diem(list_tong_100, self.w_m4, self.w_m3)
        mc_tx_tai, mc_tx_xiu, mc_tx_log = predict_maucau_tx_diem(chuoi_50_kq, self.w_tx)

        # BỘ LỌC NHIỄU (Cap limit max 20)
        bonus_tai = min(20.0, mc_xx_tai + mc_tx_tai)
        bonus_xiu = min(20.0, mc_xx_xiu + mc_tx_xiu)

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
        print(f"📘 [LOGIC: HỢP NHẤT TRỌNG SỐ, MODULO & MẪU KÉP]")
        print(f"   => Modulo 11    : TÀI {mod_tai:.1f}% | XỈU {mod_xiu:.1f}%")
        print(f"   => Trọng số 13  : TÀI {chuoi_tai:.1f}% | XỈU {chuoi_xiu:.1f}%")
        print(f"   => % Base Hợp nhất: TÀI {chia_tai:.1f}% | XỈU {chia_xiu:.1f}%")
        print(f"   => Điểm Mẫu XX  : +{round(mc_xx_tai,1)} TÀI | +{round(mc_xx_xiu,1)} XỈU (Mẫu {mc_xx_log})")
        print(f"   => Điểm Mẫu TX  : +{mc_tx_tai} TÀI | +{mc_tx_xiu} XỈU (Mẫu {mc_tx_log})")
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
                res = requests.get(API_ENDPOINT, timeout=3)
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

            except Exception: pass
            time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=lambda: SunwinLogic_Merged().run(), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
```[cite: 4]

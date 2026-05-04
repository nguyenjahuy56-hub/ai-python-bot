import time
import requests
import json
import os
import sys
import threading
import hashlib
import optuna
from flask import Flask

# Tắt log rác của Optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️ CONFIG HỆ THỐNG
# ==========================================
API_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"

HISTORY_MAX = 200          
REQUIRED_LEN = 13  # Bỏ 13 phiên đầu để lấy đủ chuỗi TX       
NGUONG_TY_LE = 3   # Ngưỡng tỷ lệ cho logic chuỗi

app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "🔥 AI Server - TỔNG HỢP MODULO + TRỌNG SỐ 13 + OPTUNA ALL-IN..."

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
    weights = [1.25**i for i in range(len(chuoi))]
    tong_weight = sum(weights)
    tai = sum(w for x, w in zip(chuoi, weights) if x == "T")
    xiu = sum(w for x, w in zip(chuoi, weights) if x == "X")
    return round(tai / tong_weight * 100, 1), round(xiu / tong_weight * 100, 1)

def dem_chuoi_lien_tiep(chuoi, ky_tu):
    count = 0
    for c in reversed(chuoi):
        if c == ky_tu: count += 1
        else: break
    return count

def phan_tich_chu_ky(chuoi):
    for l in [5, 4, 3, 2]:
        if len(chuoi) >= 2*l and chuoi[-l:] == chuoi[-2*l:-l]: return chuoi[-1]
    return None

def la_cau_dan_xen(chuoi):
    if len(chuoi) < 6: return False
    return all(chuoi[i] != chuoi[i+1] for i in range(-6, -1))

def du_doan_tu_chuoi(chuoi_50):
    chuoi = chuoi_50[-13:] if len(chuoi_50) >= 13 else chuoi_50
    perc_tai, perc_xiu = phan_tich_chuoi_weighted(chuoi)
    
    # Ở đây chúng ta chỉ lấy tỷ lệ phần trăm (perc_tai, perc_xiu) làm base trọng số
    # Các logic cộng điểm phụ của chuỗi được giản lược tập trung vào sức mạnh tỷ lệ.
    return "XONG", perc_tai, perc_xiu

# ==========================================
# 🧠 LÕI 3: MẪU CẦU XÚC XẮC 100 VÁN (DẠNG + ĐIỂM)
# ==========================================
def predict_maucau_diem(list_tong_100, w_m4=3, w_m3=1):
    if len(list_tong_100) < 4:
        return 0, 0, "[]"

    last_3 = list_tong_100[-3:]
    last_2 = list_tong_100[-2:]

    t4, x4 = 0, 0
    # Quét Mẫu 4
    for i in range(len(list_tong_100) - 3):
        if list_tong_100[i:i+3] == last_3:
            if list_tong_100[i+3] > 10: t4 += 1
            else: x4 += 1

    t3, x3 = 0, 0
    # Quét Mẫu 3
    for i in range(len(list_tong_100) - 2):
        if list_tong_100[i:i+2] == last_2:
            if list_tong_100[i+2] > 10: t3 += 1
            else: x3 += 1

    # Trả về ĐIỂM SỐ ĐỂ CỘNG VÀO DỰ ĐOÁN (Không phải dự đoán cứng)
    diem_tai = (t4 * w_m4) + (t3 * w_m3)
    diem_xiu = (x4 * w_m4) + (x3 * w_m3)
    mc_log = f"[{'-'.join(map(str, last_3))}]"
    
    return diem_tai, diem_xiu, mc_log

# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH
# ==========================================
class SunwinLogic_Merged:
    def __init__(self):
        self.file_data = "data_logic.json"
        self.last_session_id = None
        
        self.total_played = 0
        self.total_won = 0
        self.last_final_pred = None 
        self.history_predictions = {}
        
        # --- THAM SỐ TỐI ƯU CỦA OPTUNA (4 YẾU TỐ) ---
        self.w_mod = 1    # Trọng số Logic Modulo 11
        self.w_chuoi = 1  # Trọng số Logic Chuỗi 13 ván
        self.w_m4 = 3     # Điểm mẫu cầu độ dài 4
        self.w_m3 = 1     # Điểm mẫu cầu độ dài 3
        
        self.tune_counter = 0
        
        # --- HỆ THỐNG BAIT (GÃY 4 BẺ / ĐÚNG 4 TẮT) ---
        self.last_raw_pred = None     
        self.last_raw_key = None      
        self.last_raw_bucket = None   
        
        self.bait_matrix = {
            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False},
            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False, 100: False}
        }
        self.bucket_streaks = {k: {b: {'loss': 0, 'win': 0} for b in [50, 60, 70, 80, 90, 100]} for k in self.bait_matrix.keys()}
        
        self.ensure_files_exist()

    def ensure_files_exist(self):
        if not os.path.exists(self.file_data):
            with open(self.file_data, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def load_data(self):
        try:
            with open(self.file_data, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return []

    def save_data(self, data):
        try:
            with open(self.file_data, 'w', encoding='utf-8') as f: 
                json.dump(data[-HISTORY_MAX:], f, indent=2)
        except Exception as e: 
            pass

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
    # ⚙️ OPTUNA: TỐI ƯU HÓA CẢ 4 TRỌNG SỐ (CỘNG CHIA 2 + MẪU CẦU)
    # ==========================================
    def run_optuna_tuning(self, data):
        if len(data) < 30: return 
        
        print("\n🔄 [OPTUNA] Đang khởi chạy tinh chỉnh: Modulo + Trọng số TX + Mẫu Cầu...")
        
        def objective(trial):
            w_mod = trial.suggest_int('w_mod', 1, 10)
            w_chuoi = trial.suggest_int('w_chuoi', 1, 10)
            w_m4 = trial.suggest_int('w_m4', 1, 10)
            w_m3 = trial.suggest_int('w_m3', 1, 10)
            
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
                chuoi_50 = ["T" if x['tong'] > 10 else "X" for x in past_data[-50:]]
                _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50)
                
                # 3. Mẫu Cầu
                list_tong_100 = [x['tong'] for x in past_data[-100:]]
                mc_tai, mc_xiu, _ = predict_maucau_diem(list_tong_100, w_m4, w_m3)
                
                # 4. Tính toán hợp nhất (Cộng chia + Điểm Mẫu cầu)
                avg_tai = ((mod_tai * w_mod) + (chuoi_tai * w_chuoi)) / (w_mod + w_chuoi) + mc_tai
                avg_xiu = ((mod_xiu * w_mod) + (chuoi_xiu * w_chuoi)) / (w_mod + w_chuoi) + mc_xiu
                
                pred = "TÀI" if avg_tai > avg_xiu else "XỈU"
                actual = "TÀI" if data[i]['tong'] > 10 else "XỈU"
                if pred == actual:
                    correct += 1
            return correct

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=40)
        
        self.w_mod = study.best_params['w_mod']
        self.w_chuoi = study.best_params['w_chuoi']
        self.w_m4 = study.best_params['w_m4']
        self.w_m3 = study.best_params['w_m3']
        print(f"✅ [OPTUNA] Xong! W_Mod:{self.w_mod} | W_Chuoi:{self.w_chuoi} | Mẫu4:{self.w_m4} | Mẫu3:{self.w_m3}\n")

    def inject_new_data(self, phien, dice, tong):
        actual_full = "TÀI" if tong > 10 else "XỈU"

        data = self.load_data()
        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': actual_full})
        self.save_data(data)
        
        # --- THỐNG KÊ & TỐI ƯU ---
        if self.last_final_pred is not None:
            self.total_played += 1
            self.tune_counter += 1
            
            if self.last_final_pred == actual_full:
                self.total_won += 1
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💰 Ván trước HÚP {actual_full}! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
            else:
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💀 Ván trước GÃY! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
                
            # Đạt 8 ván (như cấu hình cũ) -> Tune Optuna
            if self.tune_counter >= 8:
                self.tune_counter = 0
                self.run_optuna_tuning(data)
        
        # --- MA TRẬN BẺ CẦU ---
        if self.last_raw_key is not None and self.last_raw_bucket is not None:
            raw_was_correct = (self.last_raw_pred == actual_full) 
            matrix_key = self.last_raw_key
            bucket = self.last_raw_bucket
            streak = self.bucket_streaks[matrix_key][bucket]
            
            if not self.bait_matrix[matrix_key][bucket]:
                if not raw_was_correct:
                    streak['loss'] += 1
                    streak['win'] = 0
                    if streak['loss'] >= 4:
                        self.bait_matrix[matrix_key][bucket] = True
                        streak['loss'] = 0
                        print(f"🚨 [MA TRẬN] {matrix_key} {bucket}% GÃY 4 TAY LIÊN TIẾP! BẬT CHẾ ĐỘ BẺ CẦU.")
                else: streak['loss'] = 0
            else:
                if raw_was_correct:
                    streak['win'] += 1
                    streak['loss'] = 0
                    if streak['win'] >= 4:
                        self.bait_matrix[matrix_key][bucket] = False
                        streak['win'] = 0
                        print(f"✅ [MA TRẬN] Cầu {matrix_key} {bucket}% chuẩn form 4 tay! TẮT BẺ CẦU.")
                else: streak['win'] = 0
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

        # 2. Dữ liệu Trọng Số 13 Ván
        chuoi_50 = ["T" if item['tong'] > 10 else "X" for item in data[-50:]]
        _, chuoi_tai, chuoi_xiu = du_doan_tu_chuoi(chuoi_50)

        # 3. Tính toán Chia 2 Tỉ lệ (Có áp dụng Optuna weights)
        chia_tai = ((mod_tai * self.w_mod) + (chuoi_tai * self.w_chuoi)) / (self.w_mod + self.w_chuoi)
        chia_xiu = ((mod_xiu * self.w_mod) + (chuoi_xiu * self.w_chuoi)) / (self.w_mod + self.w_chuoi)

        # 4. Cộng Điểm Mẫu Cầu
        list_tong_100 = [item['tong'] for item in data[-100:]]
        mc_tai, mc_xiu, mc_log = predict_maucau_diem(list_tong_100, self.w_m4, self.w_m3)

        # Hợp nhất Toán học cuối cùng
        final_tai = chia_tai + mc_tai
        final_xiu = chia_xiu + mc_xiu

        # CHỐT GỐC (Bên nào lớn hơn đoán bên đó)
        if final_tai > final_xiu:
            chot_goc = "TÀI"
            conf_percent = min(100.0, round(final_tai, 1))
        else:
            chot_goc = "XỈU"
            conf_percent = min(100.0, round(final_xiu, 1))
            
        matrix_key = chot_goc
        current_bucket = self.get_confidence_bucket(conf_percent)

        # In Log Logic
        print(f"📘 [LOGIC: HỢP NHẤT TRỌNG SỐ & MODULO]")
        print(f"   => Modulo 11    : TÀI {mod_tai:.1f}% | XỈU {mod_xiu:.1f}%")
        print(f"   => Trọng số 13  : TÀI {chuoi_tai:.1f}% | XỈU {chuoi_xiu:.1f}%")
        print(f"   => Tỉ lệ Chia 2 : TÀI {chia_tai:.1f}% | XỈU {chia_xiu:.1f}% (Đã nhân hệ số W)")
        print(f"   => Điểm Mẫu Cầu : +{mc_tai} TÀI | +{mc_xiu} XỈU (Mẫu {mc_log})")
        print(f"   => TỔNG KẾT     : Khớp logic {chot_goc} ({conf_percent}%)")
        print(f"   => Optuna W     : [W_Mod:{self.w_mod} | W_Chuoi:{self.w_chuoi} | W_M4:{self.w_m4} | W_M3:{self.w_m3}]")
        print(f"   => Trạng thái   : [MỐC LƯU: {matrix_key} {current_bucket}%]")

        note = ""
        chot_cuoi = chot_goc
        
        # Áp dụng Ma trận Bẻ
        if self.bait_matrix[matrix_key][current_bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note = f" (⚠️ {matrix_key} mốc {current_bucket}% đang lừa -> ÉP BẺ SANG {chot_cuoi})"
        else:
            note = f" (Vào theo phân tích chia 2 tỉ lệ & mẫu cầu gốc)"

        self.last_raw_pred = chot_goc
        self.last_raw_key = matrix_key
        self.last_raw_bucket = current_bucket
        self.last_final_pred = chot_cuoi
        self.history_predictions[str(next_session_id)] = chot_cuoi
        
        print(f"{'-'*85}")
        wr_str = f" [WR Hiện tại: {(self.total_won/self.total_played)*100:.1f}%]" if self.total_played > 0 else ""
        print(f"🔥 LỆNH CHỐT CUỐI : VÀO {chot_cuoi} {note}{wr_str}")
        
        detail = f"{chot_goc} ({conf_percent:.1f}%) ➔ {note.replace('(', '').replace(')', '')}"
        self.sync_to_dashboard(next_session_id, chot_cuoi, detail)
        print(f"{'='*85}\n")

    def run(self):
        print("🚀 Khởi động TOOL (Modulo + Trọng số 13 ván + Cộng Điểm Mẫu Cầu + Optuna)...")
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

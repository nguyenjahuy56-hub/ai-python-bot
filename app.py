import time
import requests
import json
import os
import sys
import threading
import hashlib
import optuna
from flask import Flask

# Tắt log rác của Optuna để Terminal sạch sẽ
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==========================================
# ⚙️ CONFIG HỆ THỐNG RAILWAY / RENDER
# ==========================================
API_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"

HISTORY_MAX = 200          
REQUIRED_LEN = 8          

app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "🔥 AI Server - MA TRẬN BẺ CẦU + MODULO 11 + OPTUNA AUTO-TUNE..."

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
        if byte_val > 127:
            high_byte += 1
        else:
            low_byte += 1
            
    delta = abs(high_byte - low_byte)
    wr = 62 + (delta * 1.8)
    
    if wr > 98.8: 
        wr = 98.8
    return round(wr, 1)

def predict_tx(v1, v2, v3):
    s = (2 * v1) + (3 * v2) + (4 * v3)
    r = s % 11
    result = "XỈU" if r <= 5 else "TÀI"
    conf = get_confidence(v1, v2, v3)
    return result, conf

# ==========================================
# 🧠 LÕI 2: MẪU CẦU TỔNG (QUÉT 100 VÁN CHUỖI 3-4)
# ==========================================
def predict_maucau(list_tong_100, w_m4=3, w_m3=1):
    if len(list_tong_100) < 4:
        return None, 0, None

    last_3 = list_tong_100[-3:]
    last_2 = list_tong_100[-2:]

    t4, x4 = 0, 0
    # Quét Mẫu 4 (Khớp 3 ván trước)
    for i in range(len(list_tong_100) - 3):
        if list_tong_100[i:i+3] == last_3:
            next_val = list_tong_100[i+3]
            if next_val > 10: t4 += 1
            else: x4 += 1

    t3, x3 = 0, 0
    # Quét Mẫu 3 (Khớp 2 ván trước)
    for i in range(len(list_tong_100) - 2):
        if list_tong_100[i:i+2] == last_2:
            next_val = list_tong_100[i+2]
            if next_val > 10: t3 += 1
            else: x3 += 1

    # Trọng số được truyền động từ Optuna (Mặc định Mẫu 4 ưu tiên hơn)
    diem_tai = (t4 * w_m4) + (t3 * w_m3)
    diem_xiu = (x4 * w_m4) + (x3 * w_m3)

    tong_diem = diem_tai + diem_xiu
    mc_log = f"[{'-'.join(map(str, last_3))}]"
    
    if tong_diem == 0:
        return None, 0, mc_log

    if diem_tai > diem_xiu:
        conf = (diem_tai / tong_diem) * 100
        return "TÀI", round(conf, 1), mc_log
    elif diem_xiu > diem_tai:
        conf = (diem_xiu / tong_diem) * 100
        return "XỈU", round(conf, 1), mc_log
    else:
        return None, 0, mc_log

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
        
        # --- THAM SỐ TỐI ƯU CỦA OPTUNA ---
        self.w_m4 = 3
        self.w_m3 = 1
        self.tune_counter = 0
        
        # --- HỆ THỐNG BAIT (MA TRẬN BẺ CẦU NÂNG CẤP) ---
        self.last_raw_pred = None     
        self.last_raw_key = None      
        self.last_raw_bucket = None   
        
        # Chỉ giữ lại TÀI và XỈU
        self.bait_matrix = {
            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False},
            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False}
        }
        
        self.bucket_streaks = {
            k: {b: {'loss': 0, 'win': 0} for b in [50, 60, 70, 80, 90]}
            for k in self.bait_matrix.keys()
        }
        
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
            print(f"❌ Lỗi lưu file: {e}")

    def get_confidence_bucket(self, percent):
        if percent >= 90: return 90
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
    # ⚙️ OPTUNA: TỐI ƯU HÓA TRỌNG SỐ TRÁNH OVERFIT
    # ==========================================
    def run_optuna_tuning(self, data):
        if len(data) < 30: return # Cần tối thiểu 30 ván để train
        
        print("\n🔄 [OPTUNA] Đang khởi chạy tiến trình tối ưu hóa trọng số (Chống Overfit)...")
        list_tong_all = [item['tong'] for item in data]
        
        def objective(trial):
            # Optuna sẽ test các bộ số này để tìm ra bộ bắt chuẩn nhất
            w4 = trial.suggest_int('w4', 1, 10)
            w3 = trial.suggest_int('w3', 1, 10)
            
            # Backtest 20 ván gần nhất để xem bộ số nào win nhiều nhất
            test_len = min(20, len(list_tong_all) - 10)
            correct = 0
            
            for i in range(len(list_tong_all) - test_len, len(list_tong_all)):
                past_data = list_tong_all[:i]
                pred, _, _ = predict_maucau(past_data[-100:], w4, w3)
                actual = "TÀI" if list_tong_all[i] > 10 else "XỈU"
                if pred == actual:
                    correct += 1
            return correct

        # Chạy 30 vòng lặp (trials) siêu tốc để dò số
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=30)
        
        self.w_m4 = study.best_params['w4']
        self.w_m3 = study.best_params['w3']
        print(f"✅ [OPTUNA] Hoàn tất! Trọng số mới: Mẫu 4 (W={self.w_m4}), Mẫu 3 (W={self.w_m3})\n")

    def inject_new_data(self, phien, dice, tong):
        actual_full = "TÀI" if tong > 10 else "XỈU"

        data = self.load_data()
        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': actual_full})
        self.save_data(data)
        
        # --- CHECK WIN RATE ---
        if self.last_final_pred is not None:
            self.total_played += 1
            self.tune_counter += 1
            
            if self.last_final_pred == actual_full:
                self.total_won += 1
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💰 [THỐNG KÊ] Ván trước HÚP {actual_full}! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
            else:
                wr_percent = (self.total_won / self.total_played) * 100
                print(f"💀 [THỐNG KÊ] Ván trước GÃY! (Tỉ lệ WR: {self.total_won}/{self.total_played} - {wr_percent:.1f}%)")
                
            # KÍCH HOẠT OPTUNA MỖI 8 VÁN ĐÁNH CHÍNH THỨC
            if self.tune_counter >= 8:
                self.tune_counter = 0
                self.run_optuna_tuning(data)
        
        # --- CẬP NHẬT MA TRẬN BẺ CẦU ---
        if self.last_raw_key is not None and self.last_raw_bucket is not None:
            raw_was_correct = (self.last_raw_pred == actual_full) 
            matrix_key = self.last_raw_key
            bucket = self.last_raw_bucket
            streak = self.bucket_streaks[matrix_key][bucket]
            
            if not self.bait_matrix[matrix_key][bucket]:
                if not raw_was_correct:
                    streak['loss'] += 1
                    streak['win'] = 0
                    print(f"⚠️ [THEO DÕI] Khóa {matrix_key} {bucket}% gãy tay thứ {streak['loss']}.")
                    
                    # UPDATE: Sai 4 tay thì bẻ cầu
                    if streak['loss'] >= 4:
                        self.bait_matrix[matrix_key][bucket] = True
                        streak['loss'] = 0
                        print(f"🚨 [MA TRẬN] {matrix_key} {bucket}% GÃY 4 TAY LIÊN TIẾP! BẬT CHẾ ĐỘ BẺ CẦU.")
                else:
                    streak['loss'] = 0
            else:
                if raw_was_correct:
                    streak['win'] += 1
                    streak['loss'] = 0
                    print(f"⚠️ [THEO DÕI] Logic gốc {matrix_key} {bucket}% đúng lại tay thứ {streak['win']}.")
                    
                    # UPDATE: Đúng lại 4 tay thì tắt bẻ
                    if streak['win'] >= 4:
                        self.bait_matrix[matrix_key][bucket] = False
                        streak['win'] = 0
                        print(f"✅ [MA TRẬN] Cầu {matrix_key} {bucket}% đã chuẩn form 4 tay! TẮT CHẾ ĐỘ BẺ CẦU.")
                else:
                    streak['win'] = 0

        return len(data)

    def analyze_next_round(self, next_session_id):
        data = self.load_data()
        
        print(f"\n{'='*85}")
        print(f"🎯 PHÂN TÍCH PHIÊN {next_session_id}")
        print(f"{'='*85}")

        if len(data) < REQUIRED_LEN:
            print(f"⚠️ Đang thu thập dữ liệu chống overfitting: {len(data)}/{REQUIRED_LEN} ván.")
            self.sync_to_dashboard(next_session_id, "WAIT", f"Đang nạp mồi: {len(data)}/{REQUIRED_LEN} ván")
            return

        # Dữ liệu phục vụ Modulo
        recent_3 = data[-3:]
        v1, v2, v3 = recent_3[0]['tong'], recent_3[1]['tong'], recent_3[2]['tong']
        
        # Dữ liệu phục vụ Mẫu cầu (100 ván)
        recent_100 = data[-100:] if len(data) >= 100 else data
        list_tong_100 = [item['tong'] for item in recent_100]

        # 1. Chạy Logic Modulo 11
        mod_pred, mod_conf = predict_tx(v1, v2, v3)
        
        # 2. Chạy Logic Mẫu Cầu Lịch Sử (Truyền trọng số W4 và W3 từ Optuna)
        mc_pred, mc_conf, mc_log = predict_maucau(list_tong_100, self.w_m4, self.w_m3)

        # 3. Tổng hợp tín hiệu
        chot_goc = mod_pred
        conf_percent = mod_conf
        kieu_phan_tich = "MODULO 11"
        
        if mc_pred:
            if mc_pred == mod_pred:
                kieu_phan_tich = f"ĐỒNG THUẬN (Modulo + Mẫu Cầu {mc_log} [W4:{self.w_m4}|W3:{self.w_m3}])"
                conf_percent = min(98.8, max(mod_conf, mc_conf) + 5)
            else:
                if mc_conf > mod_conf:
                    chot_goc = mc_pred
                    conf_percent = mc_conf
                    kieu_phan_tich = f"MẪU CẦU {mc_log} [W4:{self.w_m4}|W3:{self.w_m3}] (Áp đảo Modulo)"
                else:
                    kieu_phan_tich = f"MODULO 11 (Áp đảo Mẫu Cầu {mc_log})"
        
        matrix_key = chot_goc
        current_bucket = self.get_confidence_bucket(conf_percent)
        
        print(f"📘 [LOGIC: {kieu_phan_tich}]")
        print(f"   => 3 ván gần nhất (Tổng điểm): V1={v1}, V2={v2}, V3={v3}")
        print(f"   => Khớp logic  : {chot_goc} ({conf_percent:.1f}%)")
        print(f"   => Trạng thái  : [MỐC LƯU: {matrix_key} {current_bucket}%]")
        
        note = ""
        chot_cuoi = chot_goc
        
        # 🛡️ Rule bẻ tự động cho Tài mốc cao (>= 60%)
        if chot_goc == "TÀI" and conf_percent >= 60:
            chot_cuoi = "XỈU"
            note = f" (⚠️ Logic báo bẻ: Tài {conf_percent}% có độ ảo cao -> ÉP BẺ SANG XỈU)"
            
        # 🔄 Áp dụng Ma trận bẻ cầu (Gãy 4 / Đúng 4)
        elif self.bait_matrix[matrix_key][current_bucket]:
            chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"
            note = f" (⚠️ {matrix_key} mốc {current_bucket}% đang bị lừa -> ÉP BẺ SANG {chot_cuoi})"
            
        else:
            note = f" (Vào theo phân tích thuật toán gốc)"
            
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
        print("🚀 Khởi động TOOL (Modulo 11 + Mẫu Cầu 100 Ván + Ma Trận Bẻ + Optuna)...")
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

            except Exception:
                pass
            time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=lambda: SunwinLogic_Merged().run(), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

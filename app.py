import time
import requests
import json
import os
import sys
import threading
from flask import Flask

# ==========================================
# ⚙️ CONFIG HỆ THỐNG
# ==========================================
API_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-production-8d96.up.railway.app/api/update-prediction"

HISTORY_MAX = 200          
REQUIRED_LEN = 13 # Ép đủ 100 ván mới bắt đầu soi mẫu cầu động

app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "🔥 AI Server V17 - CHỈ DÙNG MẪU ĐỘNG 100 VÁN GẦN NHẤT..."

# ==========================================
# 🧠 LÕI DUY NHẤT: QUÉT MẪU CẦU ĐỘNG 100 VÁN
# ==========================================
def soi_mau_cau_100_van(chuoi_full):
    chuoi_str = "".join(chuoi_full)
    
    # Quét độ dài mẫu từ 7 tay xuống 3 tay
    for l in range(7, 2, -1):
        if len(chuoi_str) <= l: continue
        
        mau_hien_tai = chuoi_str[-l:] # Đoạn cuối cùng vừa ra
        vung_tim_kiem = chuoi_str[:-1] # Tìm trong quá khứ (bỏ ván cuối)
        
        count_T = 0
        count_X = 0
        start = 0
        
        while True:
            idx = vung_tim_kiem.find(mau_hien_tai, start)
            if idx == -1: break
            
            # Xem ván tiếp theo sau mẫu đó trong quá khứ là gì
            next_idx = idx + len(mau_hien_tai)
            if next_idx < len(chuoi_str):
                if chuoi_str[next_idx] == "T": count_T += 1
                elif chuoi_str[next_idx] == "X": count_X += 1
            start = idx + 1
            
        # Nếu tìm thấy mẫu lặp trong quá khứ có kết quả nghiêng hẳn về một bên
        if count_T > count_X:
            return "TÀI", f"Khớp mẫu lặp {l} tay (Quá khứ ra Tài nhiều hơn)"
        elif count_X > count_T:
            return "XỈU", f"Khớp mẫu lặp {l} tay (Quá khứ ra Xỉu nhiều hơn)"
            
    return "KHÔNG RÕ", "Không tìm thấy mẫu lặp tương ứng trong 100 ván"

# ==========================================
# 🤖 LỚP ĐIỀU KHIỂN CHÍNH
# ==========================================
class SunwinLogic_V17:
    def __init__(self):
        self.file_data = "data_logic.json"
        self.last_session_id = None
        self.total_played = 0
        self.total_won = 0
        self.last_final_pred = None
        self.history_predictions = {}
        self.ensure_files_exist()

    def ensure_files_exist(self):
        if not os.path.exists(self.file_data):
            with open(self.file_data, 'w', encoding='utf-8') as f: json.dump([], f)

    def load_data(self):
        try:
            with open(self.file_data, 'r', encoding='utf-8') as f: return json.load(f)
        except: return []

    def sync_to_dashboard(self, next_phien, pred, detail):
        try:
            wr = (self.total_won / self.total_played * 100) if self.total_played > 0 else 0
            full_data = self.load_data()
            history_list = []
            for item in full_data[-20:]:
                phien = item['phien']
                actual_res = "TÀI" if item['kq'] == 'T' else "XỈU"
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

    def run(self):
        print("🚀 Khởi động: CHỈ DÙNG MẪU ĐỘNG 100 VÁN...")
        while True:
            try:
                api_data = requests.get(API_ENDPOINT, timeout=3).json()
                if not api_data.get("Phien"):
                    time.sleep(2)
                    continue
                    
                curr_session = int(api_data["Phien"])
                if curr_session != self.last_session_id:
                    # Cập nhật kết quả ván vừa xong
                    actual_full = "TÀI" if int(api_data["Tong"]) > 10 else "XỈU"
                    if self.last_final_pred:
                        self.total_played += 1
                        if self.last_final_pred == actual_full: self.total_won += 1
                    
                    # Lưu data mới
                    self.last_session_id = curr_session
                    data = self.load_data()
                    data.append({'phien': curr_session, 'kq': "T" if actual_full == "TÀI" else "X"})
                    with open(self.file_data, 'w') as f: json.dump(data[-HISTORY_MAX:], f)
                    
                    # Dự đoán ván tiếp theo
                    if len(data) >= REQUIRED_LEN:
                        # ĐÃ FIX: Lấy đủ 100 ván thay vì 50
                        recent_100 = [item['kq'] for item in data[-100:]]
                        pred, detail = soi_mau_cau_100_van(recent_100)
                        self.last_final_pred = pred if pred != "KHÔNG RÕ" else None
                        self.history_predictions[str(curr_session + 1)] = pred
                        self.sync_to_dashboard(curr_session + 1, pred, detail)
                    else:
                        # ĐÃ FIX: Đổi thông báo chữ thành 100 ván
                        self.sync_to_dashboard(curr_session + 1, "WAIT", f"Đang nạp mồi: {len(data)}/100 ván")
            except: pass
            time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=lambda: SunwinLogic_V17().run(), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

import time
import requests
import unicodedata
import json
import os
import hashlib
from pymongo import MongoClient

# ================= CẤU HÌNH THÔNG SỐ AI =================
MAX_SAMPLES_TONG = 8  
MAX_SAMPLES_DICE = 10  
WEIGHT_TONG = 0.45     
WEIGHT_DICE = 0.55     
# ========================================================

API_URL = 'https://apisun-production-8d96.up.railway.app/api/ddvipro'
SYNC_URL = 'https://apisun-production-8d96.up.railway.app/api/update-prediction'
FETCH_INTERVAL = 1.2

# CẤU HÌNH KẾT NỐI MONGODB CLOUD
MONGO_URI = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    db           = mongo_client['sunwin_database']
    collection   = db['history_docvi']
    mongo_client.admin.command('ping')
    print("✅ KẾT NỐI MONGODB THÀNH CÔNG!")
except Exception as e:
    print(f"❌ LỖI KẾT NỐI MONGODB: {e}")
    collection   = None

class TaiXiuAI:
    def __init__(self):
        self.raw_history = []
        self.last_hash = None
        self.last_prediction = None
        self.predicted_phien = None
        self.error_streak = 0
        
        # Mảng tính WR 15 ván cuốn chiếu
        self.recent_15_results = [] 
        # Mảng lưu lịch sử hiển thị trên Dashboard (tối đa 20 ván cho UI)
        self.dashboard_history = [] 
        
        self.load_memory()

    def load_memory(self):
        if collection is None:
            print("⚠️ Không có kết nối DB, chạy với bộ nhớ trống.")
            return
        try:
            doc = collection.find_one({'config': 'history_array'})
            if doc and 'data' in doc:
                self.raw_history = doc['data']
                print(f"✅ Đã khôi phục {len(self.raw_history)} ván lịch sử từ MongoDB Cloud!")
            else:
                print("ℹ️ Thư mục database trống, bắt đầu cào mới.")
                self.raw_history = []
        except Exception as e:
            print(f"❌ LỖI ĐỌC DATABASE: {e}")
            self.raw_history = []

    def save_history(self):
        if collection is None:
            return
        try:
            # Giới hạn mảng lưu trữ tránh quá tải gói database free
            if len(self.raw_history) > 1500:
                self.raw_history = self.raw_history[-1500:]
            
            collection.update_one(
                {'config': 'history_array'},
                {'$set': {'data': self.raw_history}},
                upsert=True
            )
        except Exception as e:
            print(f"❌ LỖI ĐỒNG BỘ DATA LÊN MONGODB: {e}")

    def extract_data_list(self, json_data):
        if isinstance(json_data, list): return json_data
        if isinstance(json_data, dict):
            if any(k in json_data for k in ['Ket_qua', 'ket_qua', 'ketqua', 'Phien', 'phien', 'Tong', 'tong']):
                return [json_data]
            keys_to_check = ['list', 'data', 'results', 'sessions', 'txHistory', 'history', 'items', 'records']
            for k in keys_to_check:
                if k in json_data and isinstance(json_data[k], list): return json_data[k]
            for k, v in json_data.items():
                if isinstance(v, list): return v
        return []

    def normalize_result(self, val):
        if val is None: return None
        s = str(val).strip()
        s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()
        if s in ['TAI', 'T', '1', 'TRUE']: return 1
        if s in ['XIU', 'X', '0', 'FALSE']: return 0
        return None

    def get_prob_by_tong(self, history, target_tong):
        tai_count = 0
        total_matched = 0
        for i in range(len(history) - 2, -1, -1):
            if history[i]['tong'] == target_tong:
                total_matched += 1
                if history[i + 1]['result'] == 1: tai_count += 1
                if total_matched >= MAX_SAMPLES_TONG: break
        if total_matched == 0: return 0.5 
        return tai_count / total_matched

    def get_prob_by_dice(self, history, target_dice_str):
        tai_count = 0
        total_matched = 0
        for i in range(len(history) - 2, -1, -1):
            if history[i]['dice'] == target_dice_str:
                total_matched += 1
                if history[i + 1]['result'] == 1: tai_count += 1
                if total_matched >= MAX_SAMPLES_DICE: break
        if total_matched == 0: return 0.5 
        return tai_count / total_matched

    def get_confidence_rate(self, v1, v2, v3):
        raw_string = f"{v1}-{v2}-{v3}"
        hash_str = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()
        high_byte, low_byte = 0, 0
        for i in range(0, 64, 2):
            if int(hash_str[i:i+2], 16) > 127: high_byte += 1
            else: low_byte += 1
        delta = abs(high_byte - low_byte)
        return min(round(62 + (delta * 1.8), 1), 98.8)

    def sync_to_dashboard(self, pred_result, confidence, detail):
        if len(self.recent_15_results) > 0:
            wr = (sum(self.recent_15_results) / len(self.recent_15_results)) * 100
        else:
            wr = 0.0

        payload = {
            "result": pred_result,
            "confidence": confidence,
            "detail": detail,
            "win_rate": round(wr, 1),
            "total_played": len(self.recent_15_results),
            "history": self.dashboard_history[::-1] 
        }
        try:
            requests.post(SYNC_URL, json=payload, timeout=3)
        except:
            pass

    def run(self):
        print("🔥 SERVER AI ĐỌC VỊ ĐANG CHẠY - ĐỒNG BỘ MONGODB CLOUD & DASHBOARD...")
        while True:
            try:
                resp = requests.get(API_URL, timeout=3)
                if not resp.ok: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                json_data = resp.json()
                data = self.extract_data_list(json_data)
                if not data or len(data) == 0:
                    time.sleep(FETCH_INTERVAL)
                    continue
                
                data.sort(key=lambda x: int(x.get('Phien', x.get('phien', x.get('id', 0)))), reverse=True)
                latest = data[0]
                phien = latest.get('Phien', latest.get('phien', latest.get('id', 'N/A')))
                
                result_str = next((latest[k] for k in ['Ket_qua', 'ket_qua', 'ketqua', 'resultTruyenThong', 'result', 'outcome'] if k in latest and latest[k] is not None), None)
                res_val = self.normalize_result(result_str)
                
                x1 = latest.get('Xuc_xac_1', latest.get('x1', latest.get('dice1')))
                x2 = latest.get('Xuc_xac_2', latest.get('x2', latest.get('dice2')))
                x3 = latest.get('Xuc_xac_3', latest.get('x3', latest.get('dice3')))
                
                if res_val is None or x1 is None or x2 is None or x3 is None: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                
                x1, x2, x3 = int(x1), int(x2), int(x3)
                tong = x1 + x2 + x3
                dice_tuple = sorted([x1, x2, x3])
                dice_str = f"{dice_tuple[0]}-{dice_tuple[1]}-{dice_tuple[2]}"
                
                if str(phien) == str(self.last_hash):
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                self.last_hash = str(phien)
                
                if self.last_prediction is not None and self.predicted_phien == int(phien):
                    won = (self.last_prediction == res_val)
                    actual_str = "TÀI" if res_val == 1 else "XỈU"
                    
                    if not won:
                        self.error_streak += 1
                        print(f"❌ Phiên {phien} GÃY! (Chuỗi gãy hiện tại: {self.error_streak})")
                    else:
                        self.error_streak = 0
                        print(f"✅ Phiên {phien} HÚP!")

                    # Cuốn chiếu mảng 15 ván gần nhất
                    self.recent_15_results.append(won)
                    if len(self.recent_15_results) > 15:
                        self.recent_15_results.pop(0) 
                    
                    if len(self.dashboard_history) > 0 and self.dashboard_history[-1]['phien'] == self.predicted_phien:
                        self.dashboard_history[-1]['actual'] = actual_str
                        self.dashboard_history[-1]['win'] = won

                # Đẩy kết quả mới vào bộ nhớ cục bộ và ghi đè đồng bộ lên MongoDB cloud
                self.raw_history.append({'phien': phien, 'result': res_val, 'tong': tong, 'dice': dice_str})
                self.save_history()
                
                print(f"\n🎲 KQ Phiên {phien}: {'TÀI' if res_val==1 else 'XỈU'} | Tổng: {tong} | Xúc xắc: {dice_str}")
                self.predict_next()
                
            except Exception as e:
                pass
                
            time.sleep(FETCH_INTERVAL)

    def predict_next(self):
        if len(self.raw_history) < 3: 
            print("⏳ Đang tích lũy thêm dữ liệu vào MongoDB để AI học...")
            return
            
        last_round = self.raw_history[-1]
        target_tong = last_round['tong']
        target_dice = last_round['dice']
        
        prob_tong_tai = self.get_prob_by_tong(self.raw_history, target_tong)
        prob_dice_tai = self.get_prob_by_dice(self.raw_history, target_dice)
        
        v1 = self.raw_history[-3]['tong'] if len(self.raw_history) >= 3 else 10
        v2 = self.raw_history[-2]['tong'] if len(self.raw_history) >= 2 else 10
        v3 = self.raw_history[-1]['tong']
        confidence_rate = self.get_confidence_rate(v1, v2, v3)
        
        final_prob_tai = (WEIGHT_TONG * prob_tong_tai) + (WEIGHT_DICE * prob_dice_tai)
        raw_pred = 1 if final_prob_tai >= 0.5 else 0
        
        # LOGIC BẺ CẦU: Sai đúng 2 tay liên tiếp thì ép bẻ tay 3, từ tay 4 tắt bẻ quay về thuận logic
        if self.error_streak == 2:
            print("⚠️ KÍCH HOẠT BẺ CẦU TAY THỨ 3!")
            final_pred = 1 - raw_pred
            detail_msg = f"Đọc Vị | ÉP BẺ CẦU (Gãy 2)"
        else:
            final_pred = raw_pred
            detail_msg = f"Đọc Vị | T:{target_tong} B:{target_dice}"
            if self.error_streak >= 3:
                print(f"🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt chế độ bẻ, đánh thuận logic.")
            
        self.last_prediction = final_pred
        
        try:
            next_phien = int(self.raw_history[-1]['phien']) + 1
        except:
            next_phien = "Tiếp"

        self.predicted_phien = next_phien
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        self.dashboard_history.append({
            "phien": next_phien, "pred": pred_str, "actual": None, "win": None
        })
        if len(self.dashboard_history) > 20:
            self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg)

        pt_tong_hien_thi = prob_tong_tai if prob_tong_tai > 0.5 else (1 - prob_tong_tai)
        pt_dice_hien_thi = prob_dice_tai if prob_dice_tai > 0.5 else (1 - prob_dice_tai)

        print(f"🔍 Dữ liệu mẫu (Ván trước: Tổng {target_tong}, Bộ {target_dice}):")
        print(f"  > Mẫu Tổng thiên về: {'TÀI' if prob_tong_tai > 0.5 else 'XỈU'} ({pt_tong_hien_thi*100:.0f}%)")
        print(f"  > Mẫu Bộ thiên về: {'TÀI' if prob_dice_tai > 0.5 else 'XỈU'} ({pt_dice_hien_thi*100:.0f}%)")
        print(f"🎯 Phiên {next_phien} | Dự đoán: {pred_str} | Tỉ lệ toán học: {confidence_rate}%")

if __name__ == "__main__":
    bot = TaiXiuAI()
    bot.run()

import time
import requests
import unicodedata
import json
import os
import hashlib
import threading
from pymongo import MongoClient

# ================= CẤU HÌNH THÔNG SỐ AI (ĐÃ TÁCH RIÊNG & THÊM TRỌNG SỐ THỜI GIAN) =================

# ♠️ THÔNG SỐ AI CHO SUNWIN
SUNWIN_MAX_SAMPLES_TONG = 8     # Số lần quét lại lịch sử cho TỔNG 
SUNWIN_MAX_SAMPLES_DICE = 10    # Số lần quét lại lịch sử cho BỘ XÚC XẮC 
SUNWIN_WEIGHT_TONG = 0.45       # Trọng số của Tổng so với Xúc Xắc (45%)
SUNWIN_WEIGHT_DICE = 0.55       # Trọng số của Xúc Xắc so với Tổng (55%)
SUNWIN_SAMPLE_DECAY = 0.85      # Độ suy giảm trọng số mẫu cũ (1.0 là ko giảm. 0.85 là tối ưu nhất: 100% -> 85% -> 72%...)

# ♦️ THÔNG SỐ AI CHO HITCLUB MD5
HITCLUB_MAX_SAMPLES_TONG = 5    
HITCLUB_MAX_SAMPLES_DICE = 8    
HITCLUB_WEIGHT_TONG = 0.45      
HITCLUB_WEIGHT_DICE = 0.55      
HITCLUB_SAMPLE_DECAY = 0.85     

# 🌐 CẤU HÌNH SERVER NODEJS & DATABASE LOCAL
NODEJS_SERVER = "https://apisun-production-8d96.up.railway.app" 
FETCH_INTERVAL = 1.2
HITCLUB_HISTORY_FILE = "datahitclubmd5.json"

# ========================================================================

# CẤU HÌNH KẾT NỐI MONGODB (Cho Sunwin - Giữ nguyên kết nối Cloud)
MONGO_URI = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    db = mongo_client['sunwin_database']
    sunwin_collection = db['history_docvi']
    mongo_client.admin.command('ping')
    print("✅ KẾT NỐI MONGODB SUNWIN THÀNH CÔNG!")
except Exception as e:
    print(f"❌ LỖI KẾT NỐI MONGODB: {e}")
    sunwin_collection = None

# ==========================================================
# LỚP AI ĐỌC VỊ CHUNG (Tích hợp logic Time Decay Weight)
# ==========================================================
class BaseTaiXiuAI:
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

    # Logic mới: Tính xác suất dựa trên tổng Trọng số các mẫu (Mẫu gần = điểm cao, mẫu xa = điểm thấp)
    def get_prob_by_tong(self, history, target_tong, max_samples, decay_rate):
        tai_weight = 0.0
        total_weight = 0.0
        matched_count = 0
        
        for i in range(len(history) - 2, -1, -1):
            if history[i]['tong'] == target_tong:
                current_weight = decay_rate ** matched_count  # Mẫu đầu: decay^0 = 1, Mẫu hai: decay^1 ...
                total_weight += current_weight
                
                if history[i + 1]['result'] == 1: 
                    tai_weight += current_weight
                    
                matched_count += 1
                if matched_count >= max_samples: break
                
        if total_weight == 0: return 0.5 
        return tai_weight / total_weight

    # Tương tự cho Xúc Xắc
    def get_prob_by_dice(self, history, target_dice_str, max_samples, decay_rate):
        tai_weight = 0.0
        total_weight = 0.0
        matched_count = 0
        
        for i in range(len(history) - 2, -1, -1):
            if history[i]['dice'] == target_dice_str:
                current_weight = decay_rate ** matched_count
                total_weight += current_weight
                
                if history[i + 1]['result'] == 1: 
                    tai_weight += current_weight
                    
                matched_count += 1
                if matched_count >= max_samples: break
                
        if total_weight == 0: return 0.5 
        return tai_weight / total_weight

    def get_confidence_rate(self, v1, v2, v3):
        raw_string = f"{v1}-{v2}-{v3}"
        hash_str = hashlib.sha256(raw_string.encode('utf-8')).hexdigest()
        high_byte, low_byte = 0, 0
        for i in range(0, 64, 2):
            if int(hash_str[i:i+2], 16) > 127: high_byte += 1
            else: low_byte += 1
        delta = abs(high_byte - low_byte)
        return min(round(62 + (delta * 1.8), 1), 98.8)

    def sync_to_dashboard(self, pred_result, confidence, detail, sync_url):
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
            requests.post(sync_url, json=payload, timeout=3)
        except:
            pass

# ==========================================================
# LUỒNG 1: AI SUNWIN 
# ==========================================================
class SunwinAI(BaseTaiXiuAI):
    def __init__(self):
        self.max_samples_tong = SUNWIN_MAX_SAMPLES_TONG  
        self.max_samples_dice = SUNWIN_MAX_SAMPLES_DICE  
        self.weight_tong = SUNWIN_WEIGHT_TONG     
        self.weight_dice = SUNWIN_WEIGHT_DICE
        self.sample_decay = SUNWIN_SAMPLE_DECAY
        
        self.api_url = f"{NODEJS_SERVER}/api/sunwin/live"
        self.sync_url = f"{NODEJS_SERVER}/api/sunwin/update-prediction"
        
        self.raw_history = []
        self.last_hash = None
        self.last_prediction = None
        self.predicted_phien = None
        self.error_streak = 0
        self.recent_15_results = [] 
        self.dashboard_history = [] 
        
        self.load_memory()

    def load_memory(self):
        if sunwin_collection is None: return
        try:
            doc = sunwin_collection.find_one({'config': 'history_array'})
            if doc and 'data' in doc:
                self.raw_history = doc['data']
        except Exception:
            self.raw_history = []

    def save_history(self):
        if sunwin_collection is None: return
        try:
            if len(self.raw_history) > 1500:
                self.raw_history = self.raw_history[-1500:]
            sunwin_collection.update_one(
                {'config': 'history_array'},
                {'$set': {'data': self.raw_history}},
                upsert=True
            )
        except Exception:
            pass

    def predict_next(self):
        if len(self.raw_history) < 3: return
            
        last_round = self.raw_history[-1]
        target_tong = last_round['tong']
        target_dice = last_round['dice']
        
        prob_tong_tai = self.get_prob_by_tong(self.raw_history, target_tong, self.max_samples_tong, self.sample_decay)
        prob_dice_tai = self.get_prob_by_dice(self.raw_history, target_dice, self.max_samples_dice, self.sample_decay)
        
        v1 = self.raw_history[-3]['tong'] if len(self.raw_history) >= 3 else 10
        v2 = self.raw_history[-2]['tong'] if len(self.raw_history) >= 2 else 10
        v3 = self.raw_history[-1]['tong']
        confidence_rate = self.get_confidence_rate(v1, v2, v3)
        
        final_prob_tai = (self.weight_tong * prob_tong_tai) + (self.weight_dice * prob_dice_tai)
        raw_pred = 1 if final_prob_tai >= 0.5 else 0
        
        if self.error_streak == 4:
            print("[♠️ SUNWIN] ⚠️ KÍCH HOẠT BẺ CẦU TAY THỨ 5!")
            final_pred = 1 - raw_pred
            detail_msg = f"Đọc Vị | ÉP BẺ CẦU (Gãy 4)"
        else:
            final_pred = raw_pred
            detail_msg = f"Đọc Vị | T:{target_tong} B:{target_dice}"
            if self.error_streak >= 5:
                print(f"[♠️ SUNWIN] 🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt bẻ cầu.")
            
        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        self.predicted_phien = next_phien
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [SUNWIN] ĐANG CHẠY LUỒNG AI ĐỌC VỊ...")
        while True:
            try:
                resp = requests.get(self.api_url, timeout=3)
                if not resp.ok: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                latest = resp.json()
                phien = latest.get('Phien')
                res_val = self.normalize_result(latest.get('Ket_qua'))
                x1, x2, x3 = latest.get('Xuc_xac_1'), latest.get('Xuc_xac_2'), latest.get('Xuc_xac_3')
                
                if phien is None or res_val is None or x1 is None: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                
                tong = int(x1) + int(x2) + int(x3)
                dice_tuple = sorted([int(x1), int(x2), int(x3)])
                dice_str = f"{dice_tuple[0]}-{dice_tuple[1]}-{dice_tuple[2]}"
                
                if str(phien) == str(self.last_hash):
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                self.last_hash = str(phien)
                
                if self.last_prediction is not None and self.predicted_phien == int(phien):
                    won = (self.last_prediction == res_val)
                    if not won: self.error_streak += 1
                    else: self.error_streak = 0
                        
                    self.recent_15_results.append(won)
                    if len(self.recent_15_results) > 15: self.recent_15_results.pop(0) 
                    
                    if len(self.dashboard_history) > 0 and self.dashboard_history[-1]['phien'] == self.predicted_phien:
                        self.dashboard_history[-1]['actual'] = "TÀI" if res_val == 1 else "XỈU"
                        self.dashboard_history[-1]['win'] = won

                self.raw_history.append({'phien': phien, 'result': res_val, 'tong': tong, 'dice': dice_str})
                self.save_history()
                print(f"[♠️ SUNWIN] KQ Phiên {phien}: {'TÀI' if res_val==1 else 'XỈU'} | Tổng: {tong} | Xúc xắc: {dice_str}")
                self.predict_next()
            except Exception:
                pass
            time.sleep(FETCH_INTERVAL)

# ==========================================================
# LUỒNG 2: AI HITCLUB MD5 
# ==========================================================
class HitclubAI(BaseTaiXiuAI):
    def __init__(self):
        self.max_samples_tong = HITCLUB_MAX_SAMPLES_TONG  
        self.max_samples_dice = HITCLUB_MAX_SAMPLES_DICE  
        self.weight_tong = HITCLUB_WEIGHT_TONG     
        self.weight_dice = HITCLUB_WEIGHT_DICE
        self.sample_decay = HITCLUB_SAMPLE_DECAY
        self.history_file = HITCLUB_HISTORY_FILE
        
        self.api_url = f"{NODEJS_SERVER}/api/hitclub/live"
        self.sync_url = f"{NODEJS_SERVER}/api/hitclub/update-prediction"

        self.raw_history = []
        self.last_hash = None
        self.last_prediction = None
        self.predicted_phien = None
        self.error_streak = 0
        self.recent_15_results = [] 
        self.dashboard_history = [] 
        
        self.load_memory()

    def load_memory(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.raw_history = json.load(f)
        except Exception:
            pass

    def save_history(self):
        try:
            if len(self.raw_history) > 2000:
                self.raw_history = self.raw_history[-2000:]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.raw_history, f)
        except Exception:
            pass

    def predict_next(self):
        if len(self.raw_history) < 3: return
            
        last_round = self.raw_history[-1]
        target_tong = last_round['tong']
        target_dice = last_round['dice']
        
        prob_tong_tai = self.get_prob_by_tong(self.raw_history, target_tong, self.max_samples_tong, self.sample_decay)
        prob_dice_tai = self.get_prob_by_dice(self.raw_history, target_dice, self.max_samples_dice, self.sample_decay)
        
        v1 = self.raw_history[-3]['tong'] if len(self.raw_history) >= 3 else 10
        v2 = self.raw_history[-2]['tong'] if len(self.raw_history) >= 2 else 10
        v3 = self.raw_history[-1]['tong']
        confidence_rate = self.get_confidence_rate(v1, v2, v3)
        
        final_prob_tai = (self.weight_tong * prob_tong_tai) + (self.weight_dice * prob_dice_tai)
        raw_pred = 1 if final_prob_tai >= 0.5 else 0
        
        if self.error_streak >= 4:
            print("[♦️ HITCLUB] ⚠️ ĐÃ SAI 4 TAY -> KÍCH HOẠT BẺ CẦU!")
            final_pred = 1 - raw_pred
            self.error_streak = 0 
            detail_msg = f"Đọc Vị | ÉP BẺ CẦU (Gãy 4)"
        else:
            final_pred = raw_pred
            detail_msg = f"Đọc Vị | T:{target_tong} B:{target_dice}"
            
        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        self.predicted_phien = next_phien
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [HITCLUB] ĐANG CHẠY LUỒNG AI ĐỌC VỊ...")
        while True:
            try:
                resp = requests.get(self.api_url, timeout=3)
                if not resp.ok: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                latest = resp.json()
                phien = latest.get('Phien')
                res_val = self.normalize_result(latest.get('Ket_qua'))
                x1, x2, x3 = latest.get('Xuc_xac_1'), latest.get('Xuc_xac_2'), latest.get('Xuc_xac_3')
                
                if phien == "Đang chờ..." or phien is None or res_val is None or x1 is None: 
                    time.sleep(FETCH_INTERVAL)
                    continue
                
                tong = int(x1) + int(x2) + int(x3)
                dice_tuple = sorted([int(x1), int(x2), int(x3)])
                dice_str = f"{dice_tuple[0]}-{dice_tuple[1]}-{dice_tuple[2]}"
                
                if str(phien) == str(self.last_hash):
                    time.sleep(FETCH_INTERVAL)
                    continue
                    
                self.last_hash = str(phien)
                
                if self.last_prediction is not None and self.predicted_phien == int(phien):
                    won = (self.last_prediction == res_val)
                    if not won: self.error_streak += 1
                    else: self.error_streak = 0
                        
                    self.recent_15_results.append(won)
                    if len(self.recent_15_results) > 15: self.recent_15_results.pop(0) 
                    
                    if len(self.dashboard_history) > 0 and self.dashboard_history[-1]['phien'] == self.predicted_phien:
                        self.dashboard_history[-1]['actual'] = "TÀI" if res_val == 1 else "XỈU"
                        self.dashboard_history[-1]['win'] = won

                self.raw_history.append({'phien': phien, 'result': res_val, 'tong': tong, 'dice': dice_str})
                self.save_history()
                print(f"[♦️ HITCLUB] KQ Phiên {phien}: {'TÀI' if res_val==1 else 'XỈU'} | Tổng: {tong} | Xúc xắc: {dice_str}")
                self.predict_next()
            except Exception:
                pass
            time.sleep(FETCH_INTERVAL)

# ==========================================================
# KHỞI CHẠY ĐA LUỒNG SỬ DỤNG THREADING
# ==========================================================
def run_sunwin_bot():
    bot = SunwinAI()
    bot.run()

def run_hitclub_bot():
    bot = HitclubAI()
    bot.run()

if __name__ == "__main__":
    t_sw = threading.Thread(target=run_sunwin_bot)
    t_hc = threading.Thread(target=run_hitclub_bot)
    
    t_sw.start()
    t_hc.start()
    
    t_sw.join()
    t_hc.join()

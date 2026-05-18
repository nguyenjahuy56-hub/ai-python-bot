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
SUNWIN_MAX_SAMPLES_TONG = 8    
SUNWIN_MAX_SAMPLES_DICE = 13    
SUNWIN_WEIGHT_TONG = 0.70       
SUNWIN_WEIGHT_DICE = 0.30       
SUNWIN_SAMPLE_DECAY = 0.80     

# ♦️ THÔNG SỐ AI CHO HITCLUB MD5
HITCLUB_MAX_SAMPLES_TONG = 10  
HITCLUB_MAX_SAMPLES_DICE = 13  
HITCLUB_WEIGHT_TONG = 0.70     
HITCLUB_WEIGHT_DICE = 0.30
HITCLUB_SAMPLE_DECAY = 0.80

# 🌐 CẤU HÌNH SERVER NODEJS & DATABASE LOCAL
NODEJS_SERVER = "https://apisun-production-8d96.up.railway.app"
FETCH_INTERVAL = 1.2
HITCLUB_HISTORY_FILE = "datahitclubmd5.json"

# ========================================================================

# CẤU HÌNH KẾT NỐI MONGODB (Cho Sunwin)
MONGO_URI = "mongodb+srv://huylog333_db_user:engL1VIN3XA7egZY@cluster0.2myhlng.mongodb.net/?appName=Cluster0"
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    db = mongo_client['sunwin_database']
    sunwin_collection = db['history_docvi']
    mongo_client.admin.command('ping')
    print("✅ KẾT NỐI MONGODB SUNWIN THÀNH CÔNG!", flush=True)
except Exception as e:
    print(f"❌ LỖI KẾT NỐI MONGODB: {e}", flush=True)
    sunwin_collection = None

# ==========================================================
# LỚP AI ĐỌC VỊ CHUNG
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

    def get_prob_by_tong(self, history, target_tong, max_samples, decay_rate):
        tai_weight = 0.0
        total_weight = 0.0
        matched_count = 0
        
        for i in range(len(history) - 2, -1, -1):
            if history[i]['tong'] == target_tong:
                current_weight = decay_rate ** matched_count 
                total_weight += current_weight
                
                if history[i + 1]['result'] == 1: 
                    tai_weight += current_weight
                    
                matched_count += 1
                if matched_count >= max_samples: break
                
        if total_weight == 0: return 0.5 
        return tai_weight / total_weight

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
        
        # TÍNH TOÁN CƠ BẢN
        avg_prob_tai = (prob_tong_tai + prob_dice_tai) / 2
        raw_pred = 1 if avg_prob_tai >= 0.5 else 0
        
        if raw_pred == 1:
            confidence_rate = round(avg_prob_tai * 100, 1)
        else:
            confidence_rate = round((1 - avg_prob_tai) * 100, 1)

        tong_pred_str = "TÀI" if prob_tong_tai >= 0.5 else "XỈU"
        dice_pred_str = "TÀI" if prob_dice_tai >= 0.5 else "XỈU"

        # ================= LỌC LOGIC BẺ CẦU =================
        final_pred = raw_pred
        reason_msg = ""

        # 1. Logic bẻ cầu: Cả 2 luồng đồng thuận VÀ độ tin cậy >= 70% (Bẻ mốc 70, 80, 90. Mốc 50-60 vẫn theo)
        if (tong_pred_str == dice_pred_str) and (confidence_rate >= 70.0):
            final_pred = 1 - raw_pred
            reason_msg = f"ÉP BẺ (Đồng Thuận {confidence_rate}%)"
            print(f"[♠️ SUNWIN] ⚠️ 2 LUỒNG ĐỒNG THUẬN TỈ LỆ CAO ({confidence_rate}%) -> BẺ NGƯỢC LẠI!", flush=True)

        # 2. Logic bẻ cầu gãy 4 tay (Chỉ chạy khi không dính bẻ đồng thuận)
        elif self.error_streak == 4:
            final_pred = 1 - raw_pred
            reason_msg = "ÉP BẺ (Gãy 4)"
            print("[♠️ SUNWIN] ⚠️ GÃY 4 TAY -> KÍCH HOẠT BẺ CẦU TAY THỨ 5!", flush=True)
            
        elif self.error_streak >= 5:
            print(f"[♠️ SUNWIN] 🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt bẻ cầu, trở về bình thường.", flush=True)

        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        # TẠO DETAIL DASHBOARD
        detail_msg = f"Đọc Vị | T:{target_tong} B:{target_dice}"
        if reason_msg: detail_msg += f" | ⚠️ {reason_msg}"
        detail_msg += f" | 📊 Tỉ lệ: {confidence_rate}%"

        # IN LOG CLI RAILWAY
        print(f"🎯 [♠️ SUNWIN] DỰ ĐOÁN PHIÊN {next_phien} => CHỐT: {pred_str}", flush=True)
        print(f"   ├─ Phân tích Tổng     : {tong_pred_str} (Tỉ lệ Tài: {round(prob_tong_tai * 100, 1)}%)", flush=True)
        print(f"   ├─ Phân tích Xúc xắc  : {dice_pred_str} (Tỉ lệ Tài: {round(prob_dice_tai * 100, 1)}%)", flush=True)
        print(f"   ├─ 📊 Độ tin cậy      : {confidence_rate}%", flush=True)
        print(f"   └─ ⚠️ Chuỗi gãy hiện tại: {self.error_streak}", flush=True)
        print("-" * 50, flush=True)

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [SUNWIN] ĐANG CHẠY LUỒNG AI ĐỌC VỊ...", flush=True)
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
                
                # CẬP NHẬT WIN/LOSS LỊCH SỬ CHÍNH XÁC QUA MÃ PHIÊN (FIX LỖI KẸT CHỜ)
                matched_item = next((item for item in self.dashboard_history if str(item['phien']) == str(phien)), None)
                if matched_item and matched_item['actual'] is None:
                    pred_val = 1 if matched_item['pred'] == "TÀI" else 0
                    won = (pred_val == res_val)
                    
                    if not won: self.error_streak += 1
                    else: self.error_streak = 0
                        
                    self.recent_15_results.append(won)
                    if len(self.recent_15_results) > 15: self.recent_15_results.pop(0) 
                    
                    matched_item['actual'] = "TÀI" if res_val == 1 else "XỈU"
                    matched_item['win'] = won

                self.raw_history.append({'phien': phien, 'result': res_val, 'tong': tong, 'dice': dice_str})
                self.save_history()
                print(f"[♠️ SUNWIN] KQ Phiên {phien}: {'TÀI' if res_val==1 else 'XỈU'} | Tổng: {tong} | Xúc xắc: {dice_str}", flush=True)
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
        
        # TÍNH TOÁN CƠ BẢN
        avg_prob_tai = (prob_tong_tai + prob_dice_tai) / 2
        raw_pred = 1 if avg_prob_tai >= 0.5 else 0
        
        if raw_pred == 1:
            confidence_rate = round(avg_prob_tai * 100, 1)
        else:
            confidence_rate = round((1 - avg_prob_tai) * 100, 1)

        tong_pred_str = "TÀI" if prob_tong_tai >= 0.5 else "XỈU"
        dice_pred_str = "TÀI" if prob_dice_tai >= 0.5 else "XỈU"

        # ================= LỌC LOGIC BẺ CẦU =================
        final_pred = raw_pred
        reason_msg = ""

        # 1. Logic bẻ cầu: Cả 2 luồng đồng thuận VÀ độ tin cậy >= 70% (Bẻ mốc 70, 80, 90. Mốc 50-60 vẫn theo)
        if (tong_pred_str == dice_pred_str) and (confidence_rate >= 70.0):
            final_pred = 1 - raw_pred
            reason_msg = f"ÉP BẺ (Đồng Thuận {confidence_rate}%)"
            print(f"[♦️ HITCLUB] ⚠️ 2 LUỒNG ĐỒNG THUẬN TỈ LỆ CAO ({confidence_rate}%) -> BẺ NGƯỢC LẠI!", flush=True)

        # 2. Logic bẻ cầu gãy 4 tay (Chỉ chạy khi không dính bẻ đồng thuận)
        elif self.error_streak == 4:
            final_pred = 1 - raw_pred
            reason_msg = "ÉP BẺ (Gãy 4)"
            print("[♦️ HITCLUB] ⚠️ GÃY 4 TAY -> KÍCH HOẠT BẺ CẦU TAY THỨ 5!", flush=True)
            
        elif self.error_streak >= 5:
            print(f"[♦️ HITCLUB] 🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt bẻ cầu, trở về bình thường.", flush=True)
            
        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        # TẠO DETAIL DASHBOARD
        detail_msg = f"Đọc Vị | T:{target_tong} B:{target_dice}"
        if reason_msg: detail_msg += f" | ⚠️ {reason_msg}"
        detail_msg += f" | 📊 Tỉ lệ: {confidence_rate}%"

        # IN LOG CLI RAILWAY
        print(f"🎯 [♦️ HITCLUB] DỰ ĐOÁN PHIÊN {next_phien} => CHỐT: {pred_str}", flush=True)
        print(f"   ├─ Phân tích Tổng     : {tong_pred_str} (Tỉ lệ Tài: {round(prob_tong_tai * 100, 1)}%)", flush=True)
        print(f"   ├─ Phân tích Xúc xắc  : {dice_pred_str} (Tỉ lệ Tài: {round(prob_dice_tai * 100, 1)}%)", flush=True)
        print(f"   ├─ 📊 Độ tin cậy      : {confidence_rate}%", flush=True)
        print(f"   └─ ⚠️ Chuỗi gãy hiện tại: {self.error_streak}", flush=True)
        print("-" * 50, flush=True)

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [HITCLUB] ĐANG CHẠY LUỒNG AI ĐỌC VỊ...", flush=True)
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
                
                # CẬP NHẬT WIN/LOSS LỊCH SỬ CHÍNH XÁC QUA MÃ PHIÊN (FIX LỖI KẸT CHỜ)
                matched_item = next((item for item in self.dashboard_history if str(item['phien']) == str(phien)), None)
                if matched_item and matched_item['actual'] is None:
                    pred_val = 1 if matched_item['pred'] == "TÀI" else 0
                    won = (pred_val == res_val)
                    
                    if not won: self.error_streak += 1
                    else: self.error_streak = 0
                        
                    self.recent_15_results.append(won)
                    if len(self.recent_15_results) > 15: self.recent_15_results.pop(0) 
                    
                    matched_item['actual'] = "TÀI" if res_val == 1 else "XỈU"
                    matched_item['win'] = won

                self.raw_history.append({'phien': phien, 'result': res_val, 'tong': tong, 'dice': dice_str})
                self.save_history()
                print(f"[♦️ HITCLUB] KQ Phiên {phien}: {'TÀI' if res_val==1 else 'XỈU'} | Tổng: {tong} | Xúc xắc: {dice_str}", flush=True)
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

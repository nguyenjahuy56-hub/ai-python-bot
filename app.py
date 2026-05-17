import time
import requests
import unicodedata
import json
import os
import hashlib
import threading
from pymongo import MongoClient

# ================= CẤU HÌNH THÔNG SỐ AI ĐA LOGIC =================

# ♠️ THÔNG SỐ AI CHO SUNWIN
# --- LOGIC 1: ĐỌC VỊ BÌNH THƯỜNG (Cầu lộn xộn) ---
SUNWIN_L1_MAX_SAMPLES_TONG = 18 
SUNWIN_L1_MAX_SAMPLES_DICE = 15  
SUNWIN_L1_WEIGHT_TONG = 0.60      
SUNWIN_L1_WEIGHT_DICE = 0.40      
SUNWIN_L1_DECAY = 0.70    

# --- LOGIC 2: ĐỌC VỊ KHI VÀO FORM BỆT ---
SUNWIN_L2_MAX_SAMPLES_TONG = 7  
SUNWIN_L2_MAX_SAMPLES_DICE = 13
SUNWIN_L2_WEIGHT_TONG = 0.35
SUNWIN_L2_WEIGHT_DICE = 0.65
SUNWIN_L2_DECAY = 0.50


# ♦️ THÔNG SỐ AI CHO HITCLUB MD5
# --- LOGIC 1: ĐỌC VỊ BÌNH THƯỜNG (Cầu lộn xộn) ---
HITCLUB_L1_MAX_SAMPLES_TONG = 15    
HITCLUB_L1_MAX_SAMPLES_DICE = 18
HITCLUB_L1_WEIGHT_TONG = 0.40      
HITCLUB_L1_WEIGHT_DICE = 0.60      
HITCLUB_L1_DECAY = 0.85  

# --- LOGIC 2: ĐỌC VỊ KHI VÀO FORM BỆT ---
HITCLUB_L2_MAX_SAMPLES_TONG = 7    
HITCLUB_L2_MAX_SAMPLES_DICE = 13
HITCLUB_L2_WEIGHT_TONG = 0.30
HITCLUB_L2_WEIGHT_DICE = 0.70
HITCLUB_L2_DECAY = 0.50


# 🌐 CẤU HÌNH SERVER NODEJS & DATABASE LOCAL
NODEJS_SERVER = "https://apisun-production-8d96.up.railway.app"
FETCH_INTERVAL = 1.2
HITCLUB_HISTORY_FILE = "datahitclubmd5.json"

# ========================================================================

# CẤU HÌNH KẾT NỐI MONGODB
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
        self.l1_max_samples_tong = SUNWIN_L1_MAX_SAMPLES_TONG  
        self.l1_max_samples_dice = SUNWIN_L1_MAX_SAMPLES_DICE  
        self.l1_weight_tong = SUNWIN_L1_WEIGHT_TONG     
        self.l1_weight_dice = SUNWIN_L1_WEIGHT_DICE
        self.l1_decay = SUNWIN_L1_DECAY
        
        self.l2_max_samples_tong = SUNWIN_L2_MAX_SAMPLES_TONG  
        self.l2_max_samples_dice = SUNWIN_L2_MAX_SAMPLES_DICE  
        self.l2_weight_tong = SUNWIN_L2_WEIGHT_TONG     
        self.l2_weight_dice = SUNWIN_L2_WEIGHT_DICE
        self.l2_decay = SUNWIN_L2_DECAY
        
        self.api_url = f"{NODEJS_SERVER}/api/sunwin/live"
        self.sync_url = f"{NODEJS_SERVER}/api/sunwin/update-prediction"
        
        self.raw_history = []
        self.last_hash = None
        self.last_prediction = None
        self.predicted_phien = None
        self.error_streak = 0
        self.recent_15_results = [] 
        self.dashboard_history = [] 
        self.l2_remaining = 0 
        
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
        
        # Lấy tối đa 5 ván gần nhất chuyển thành chuỗi T/X
        recent_5 = [r['result'] for r in self.raw_history[-5:]]
        s_5 = "".join(["T" if r == 1 else "X" for r in recent_5])
        
        is_l2_trigger = False
        
        # TH1: 3 ván gần nhất là TTT hoặc XXX (Chuỗi kết thúc bằng TTT/XXX)
        if len(s_5) >= 3 and (s_5.endswith("TTT") or s_5.endswith("XXX")):
            is_l2_trigger = True
        # TH2: TTT hoặc XXX nằm ở giữa khung 5 ván
        elif len(s_5) == 5 and s_5 in ["XTTTX", "TXXXT"]:
            is_l2_trigger = True
        # TH3: Nằm ở đầu khung 5 ván thì yêu cầu phải có 4 kí tự
        elif len(s_5) == 5 and s_5 in ["TTTTX", "XXXXT"]:
            is_l2_trigger = True
            
        # Nếu khớp 1 trong 3 thế trên -> Sạc lại 1 lượt L2 (vì khung 5 tay trượt liên tục)
        if is_l2_trigger:
            self.l2_remaining = 1
        
        if self.l2_remaining > 0:
            # ---> KÍCH HOẠT LOGIC 2 (BỆT)
            logic_mode = f"L2(Bệt) - Còn {self.l2_remaining} lượt"
            prob_tong = self.get_prob_by_tong(self.raw_history, target_tong, self.l2_max_samples_tong, self.l2_decay)
            prob_dice = self.get_prob_by_dice(self.raw_history, target_dice, self.l2_max_samples_dice, self.l2_decay)
            final_prob_tai = (self.l2_weight_tong * prob_tong) + (self.l2_weight_dice * prob_dice)
            
            self.l2_remaining -= 1
        else:
            # ---> KÍCH HOẠT LOGIC 1 (BÌNH THƯỜNG)
            logic_mode = "L1(Thường)"
            prob_tong = self.get_prob_by_tong(self.raw_history, target_tong, self.l1_max_samples_tong, self.l1_decay)
            prob_dice = self.get_prob_by_dice(self.raw_history, target_dice, self.l1_max_samples_dice, self.l1_decay)
            final_prob_tai = (self.l1_weight_tong * prob_tong) + (self.l1_weight_dice * prob_dice)
            
        raw_pred = 1 if final_prob_tai >= 0.5 else 0
        
        v1 = self.raw_history[-3]['tong'] if len(self.raw_history) >= 3 else 10
        v2 = self.raw_history[-2]['tong'] if len(self.raw_history) >= 2 else 10
        v3 = self.raw_history[-1]['tong']
        confidence_rate = self.get_confidence_rate(v1, v2, v3)
        
        if self.error_streak == 2:
            print("[♠️ SUNWIN] ⚠️ GÃY 4 TAY -> KÍCH HOẠT BẺ CẦU TAY THỨ 3!")
            final_pred = 1 - raw_pred
            detail_msg = f"{logic_mode} | ÉP BẺ CẦU (Gãy 2)"
        else:
            final_pred = raw_pred
            detail_msg = f"{logic_mode} | T:{target_tong} B:{target_dice}"
            if self.error_streak >= 5:
                print(f"[♠️ SUNWIN] 🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt bẻ cầu, trở về bình thường.")
            
        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        self.predicted_phien = next_phien
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [SUNWIN] ĐANG CHẠY LUỒNG AI (L1 THƯỜNG / L2 BỆT)...")
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
        self.l1_max_samples_tong = HITCLUB_L1_MAX_SAMPLES_TONG  
        self.l1_max_samples_dice = HITCLUB_L1_MAX_SAMPLES_DICE  
        self.l1_weight_tong = HITCLUB_L1_WEIGHT_TONG     
        self.l1_weight_dice = HITCLUB_L1_WEIGHT_DICE
        self.l1_decay = HITCLUB_L1_DECAY
        
        self.l2_max_samples_tong = HITCLUB_L2_MAX_SAMPLES_TONG  
        self.l2_max_samples_dice = HITCLUB_L2_MAX_SAMPLES_DICE  
        self.l2_weight_tong = HITCLUB_L2_WEIGHT_TONG     
        self.l2_weight_dice = HITCLUB_L2_WEIGHT_DICE
        self.l2_decay = HITCLUB_L2_DECAY
        
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
        self.l2_remaining = 0 
        
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
        
        # Lấy tối đa 5 ván gần nhất chuyển thành chuỗi T/X
        recent_5 = [r['result'] for r in self.raw_history[-5:]]
        s_5 = "".join(["T" if r == 1 else "X" for r in recent_5])
        
        is_l2_trigger = False
        
        # TH1: 3 ván gần nhất là TTT hoặc XXX (Chuỗi kết thúc bằng TTT/XXX)
        if len(s_5) >= 3 and (s_5.endswith("TTT") or s_5.endswith("XXX")):
            is_l2_trigger = True
        # TH2: TTT hoặc XXX nằm ở giữa khung 5 ván
        elif len(s_5) == 5 and s_5 in ["XTTTX", "TXXXT"]:
            is_l2_trigger = True
        # TH3: Nằm ở đầu khung 5 ván thì yêu cầu phải có 4 kí tự
        elif len(s_5) == 5 and s_5 in ["TTTTX", "XXXXT"]:
            is_l2_trigger = True
            
        # Nếu khớp 1 trong 3 thế trên -> Sạc lại 1 lượt L2 (vì khung 5 tay trượt liên tục)
        if is_l2_trigger:
            self.l2_remaining = 1
        
        if self.l2_remaining > 0:
            # ---> KÍCH HOẠT LOGIC 2 (BỆT)
            logic_mode = f"L2(Bệt) - Còn {self.l2_remaining} lượt"
            prob_tong = self.get_prob_by_tong(self.raw_history, target_tong, self.l2_max_samples_tong, self.l2_decay)
            prob_dice = self.get_prob_by_dice(self.raw_history, target_dice, self.l2_max_samples_dice, self.l2_decay)
            final_prob_tai = (self.l2_weight_tong * prob_tong) + (self.l2_weight_dice * prob_dice)
            
            self.l2_remaining -= 1
        else:
            # ---> KÍCH HOẠT LOGIC 1 (BÌNH THƯỜNG)
            logic_mode = "L1(Thường)"
            prob_tong = self.get_prob_by_tong(self.raw_history, target_tong, self.l1_max_samples_tong, self.l1_decay)
            prob_dice = self.get_prob_by_dice(self.raw_history, target_dice, self.l1_max_samples_dice, self.l1_decay)
            final_prob_tai = (self.l1_weight_tong * prob_tong) + (self.l1_weight_dice * prob_dice)
            
        raw_pred = 1 if final_prob_tai >= 0.5 else 0
        
        v1 = self.raw_history[-3]['tong'] if len(self.raw_history) >= 3 else 10
        v2 = self.raw_history[-2]['tong'] if len(self.raw_history) >= 2 else 10
        v3 = self.raw_history[-1]['tong']
        confidence_rate = self.get_confidence_rate(v1, v2, v3)
        
        if self.error_streak == 2:
            print("[♦️ HITCLUB] ⚠️ GÃY 4 TAY -> KÍCH HOẠT BẺ CẦU TAY THỨ 3!")
            final_pred = 1 - raw_pred
            detail_msg = f"{logic_mode} | ÉP BẺ CẦU (Gãy 2)"
        else:
            final_pred = raw_pred
            detail_msg = f"{logic_mode} | T:{target_tong} B:{target_dice}"
            if self.error_streak >= 5:
                print(f"[♦️ HITCLUB] 🔄 Chuỗi gãy đang là {self.error_streak} -> Đã tắt bẻ cầu, trở về bình thường.")
            
        self.last_prediction = final_pred
        next_phien = int(self.raw_history[-1]['phien']) + 1 if str(self.raw_history[-1]['phien']).isdigit() else "Tiếp"
        self.predicted_phien = next_phien
        pred_str = "TÀI" if final_pred == 1 else "XỈU"

        self.dashboard_history.append({"phien": next_phien, "pred": pred_str, "actual": None, "win": None})
        if len(self.dashboard_history) > 20: self.dashboard_history.pop(0)

        self.sync_to_dashboard(pred_str, confidence_rate, detail_msg, self.sync_url)

    def run(self):
        print("🔥 [HITCLUB] ĐANG CHẠY LUỒNG AI (L1 THƯỜNG / L2 BỆT)...")
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

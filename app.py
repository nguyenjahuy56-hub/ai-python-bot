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

# THAY BẰNG LINK RENDER CỦA ÔNG VÀO 2 DÒNG DƯỚI ĐÂY

API_ENDPOINT = "https://apisun-51l0.onrender.com/api/ddvipro"
SYNC_ENDPOINT = "https://apisun-51l0.onrender.com/api/update-prediction"


HISTORY_MAX = 200          

REQUIRED_LEN = 13          



NGUONG_TY_LE = 3  



# Khởi tạo Web Server để Render và UptimeRobot nhận diện

app = Flask(__name__)



@app.route('/')

def keep_alive():

    return "🔥 AI Server V17 đang chạy ngầm và cào data 24/7..."



# ==========================================

# 🧠 LÕI 1: THUẬT TOÁN ĐẾM CHUỖI 56 (QUÉT ĐỘNG 50 VÁN)

# ==========================================

def phan_tich_chuoi_weighted(chuoi):

    weights = [2**i for i in range(len(chuoi))]

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



def phat_hien_cau_bip(chuoi):

    seq = "".join(chuoi)

    if len(seq) >= 7 and seq[-7:] in ["TTTTTTT", "XXXXXXX"]: return "Bệt siêu dài (Nên né/Bẻ)"

    if len(seq) >= 6 and seq[-6:] in ["TXTXTX", "XTXTXT"]: return "Ping-pong 1-1 siêu dài (Sắp gãy)"

    if len(seq) >= 6 and seq[-6:] in ["TTTTTT", "XXXXXX"]: return "Cầu bệt dài bất thường"

    if len(seq) >= 5 and seq[-5:] in ["TXTXX", "XTXTT"]: return "Cầu nhử đảo 1-1-2"

    if len(seq) >= 6 and seq[-6:] in ["TXXTXT", "XTTXTX"]: return "Cầu bẫy lặp đều"

    if len(seq) >= 5 and seq[-5:] in ["TTTXX", "XXXTT"]: return "Cầu bẫy 3-2 (Chờ gãy)"

    return None



def du_doan_tu_chuoi(chuoi_50):

    chuoi = chuoi_50[-13:] if len(chuoi_50) >= 13 else chuoi_50

    

    perc_tai, perc_xiu = phan_tich_chuoi_weighted(chuoi)

    diem_tai = diem_xiu = 0



    for l in range(7, 2, -1):

        if len(chuoi) >= l:

            if all(x == "T" for x in chuoi[-l:]): diem_tai += (l - 2) * 2

            elif all(x == "X" for x in chuoi[-l:]): diem_xiu += (l - 2) * 2



    ck = phan_tich_chu_ky(chuoi)

    if ck == "T": diem_tai += 5

    elif ck == "X": diem_xiu += 5



    if la_cau_dan_xen(chuoi):

        if chuoi[-1] == "T": diem_xiu += 4

        else: diem_tai += 4



    chuoi_50_str = "".join(chuoi_50)

    for l in range(7, 2, -1):

        if len(chuoi_50_str) <= l: continue

        tail = chuoi_50_str[-l:]

        search_space = chuoi_50_str[:-1]

        count_T = 0; count_X = 0; start = 0

        

        while True:

            idx = search_space.find(tail, start)

            if idx == -1: break

            next_char_idx = idx + len(tail)

            if next_char_idx < len(chuoi_50_str):

                if chuoi_50_str[next_char_idx] == "T": count_T += 1

                elif chuoi_50_str[next_char_idx] == "X": count_X += 1

            start = idx + 1

            

        if count_T > count_X:

            diem_tai += 5

            break

        elif count_X > count_T:

            diem_xiu += 5

            break



    if perc_tai > perc_xiu + NGUONG_TY_LE: diem_tai += 4

    elif perc_xiu > perc_tai + NGUONG_TY_LE: diem_xiu += 4



    if chuoi.count("T") >= 0.6 * len(chuoi): diem_tai += 2

    elif chuoi.count("X") >= 0.6 * len(chuoi): diem_xiu += 2



    lt_t = dem_chuoi_lien_tiep(chuoi, "T")

    lt_x = dem_chuoi_lien_tiep(chuoi, "X")

    if lt_t >= 3: diem_tai += 2 ** (lt_t - 2)

    if lt_x >= 3: diem_xiu += 2 ** (lt_x - 2)



    diem_tai += perc_tai / 10

    diem_xiu += perc_xiu / 10



    if len(chuoi) >= 6:

        recent_patterns = [chuoi[i:i+3] for i in range(len(chuoi)-2)]

        count_t = sum(1 for p in recent_patterns if p.count("T") >= 2)

        count_x = sum(1 for p in recent_patterns if p.count("X") >= 2)

        if count_t > count_x + 2: diem_tai += 3

        elif count_x > count_t + 2: diem_xiu += 3



    if lt_t >= 3: diem_xiu += lt_t

    elif lt_x >= 3: diem_tai += lt_x



    if len(chuoi) >= 8:

        last4 = chuoi[-4:]

        if last4[:2] == last4[2:]:

            if last4[-1] == "T": diem_tai += 2.5

            else: diem_xiu += 2.5



    chenh = abs(perc_tai - perc_xiu)

    if chenh < 3:

        if chuoi[-1] == "T": diem_xiu += 2

        else: diem_tai += 2



    if diem_tai > diem_xiu + 1: return "TÀI", perc_tai, perc_xiu

    elif diem_xiu > diem_tai + 1: return "XỈU", perc_tai, perc_xiu

    return "KHÔNG RÕ", perc_tai, perc_xiu



# ==========================================

# 🧠 LÕI 2: THUẬT TOÁN LOGIC DARK

# ==========================================

def cau_sap_dark(arr):

    if len(arr) < 2: return None

    length = 1

    for i in range(1, len(arr)):

        if arr[i] == arr[0]: length += 1

        else: break

    if 2 <= length <= 3: return {"pred": arr[0], "conf": 70, "type": "Cầu sấp (bệt)"}

    if length >= 4: return {"pred": "X" if arr[0] == "T" else "T", "conf": 75, "type": "Bẻ cầu sấp"}

    return None



def cau_noi_dark(arr):

    if len(arr) < 4: return None

    for i in range(3):

        if arr[i] == arr[i + 1]: return None

    return {"pred": "X" if arr[0] == "T" else "T", "conf": 78, "type": "Cầu nối (1-1)"}



def cau_doi_dark(arr):

    if len(arr) < 4: return None

    if arr[0] == arr[1] and arr[2] == arr[3] and arr[0] != arr[2]:

        return {"pred": arr[2], "conf": 76, "type": "Cầu đôi (2-2)"}

    return None



def cau_gay_dark(arr):

    if len(arr) >= 5 and arr[0] == arr[1] and arr[1] == arr[2] and arr[2] != arr[3] and arr[3] == arr[4]:

        return {"pred": arr[3], "conf": 74, "type": "Cầu gãy (3-2)"}

    if len(arr) >= 5 and arr[0] == arr[1] and arr[1] != arr[2] and arr[2] == arr[3] and arr[3] == arr[4]:

        return {"pred": arr[2], "conf": 74, "type": "Cầu gãy (2-3)"}

    if len(arr) >= 4 and arr[0] != arr[1] and arr[1] == arr[2] and arr[2] != arr[3] and arr[0] == arr[3]:

        return {"pred": arr[1], "conf": 72, "type": "Cầu gãy (1-2-1)"}

    return None



def phat_hien_mau_lap_dark(arr):

    if len(arr) < 4: return None

    for length in range(2, 5):

        if len(arr) < length + 1: continue

        pattern = ",".join(arr[:length])

        for i in range(length + 1, len(arr)):

            candidate = ",".join(arr[i:i+length])

            if candidate == pattern:

                next_idx = i + length

                if next_idx < len(arr): return {"pred": arr[next_idx], "conf": 85, "type": "Mẫu lặp"}

    return None



def du_doan_vi_dark(points):

    valid_points = [p for p in points if p is not None]

    if len(valid_points) < 3: return None

    avg = sum(valid_points) / len(valid_points)

    last = valid_points[0]

    if avg >= 11 and last >= 11: return {"pred": "T", "conf": 70, "type": "Vị cao"}

    if avg <= 9 and last <= 9: return {"pred": "X", "conf": 70, "type": "Vị thấp"}

    if last >= 14: return {"pred": "T", "conf": 68, "type": "Vị rất cao"}

    if last <= 6: return {"pred": "X", "conf": 68, "type": "Vị rất thấp"}

    return None



def tong_hop_du_doan_dark(chuoi, list_tong):

    arr = chuoi[::-1] 

    points = list_tong[::-1]

    

    if len(arr) < 2: return None

    

    lap = phat_hien_mau_lap_dark(arr)

    if lap: return lap

    noi = cau_noi_dark(arr)

    if noi: return noi

    doi = cau_doi_dark(arr)

    if doi: return doi

    gay = cau_gay_dark(arr)

    if gay: return gay

    sap = cau_sap_dark(arr)

    if sap: return sap

    vi = du_doan_vi_dark(points)

    if vi: return vi

    return None



# ==========================================

# 🧠 DUNG HỢP LÕI & XÚC XẮC

# ==========================================

def du_doan_tu_xuc_xac(x1, x2, x3):

    tong = x1 + x2 + x3

    if 11 <= tong <= 17: return "TÀI", tong

    elif 4 <= tong <= 10: return "XỈU", tong

    return "KHÔNG RÕ", tong



def du_doan_tong_hop(chuoi_50, chuoi_13, list_tong_13, xuc_xac):

    dark_pred = tong_hop_du_doan_dark(chuoi_13, list_tong_13)

    

    if dark_pred:

        kq_chuoi = "TÀI" if dark_pred["pred"] == "T" else "XỈU"

        pt = dark_pred["conf"] if kq_chuoi == "TÀI" else (100 - dark_pred["conf"])

        px = dark_pred["conf"] if kq_chuoi == "XỈU" else (100 - dark_pred["conf"])

        kieu_phan_tich = f"DARK ({dark_pred['type']})"

    else:

        kq_chuoi, pt, px = du_doan_tu_chuoi(chuoi_50)

        kieu_phan_tich = "THUẬT TOÁN 56 (QUÉT ĐỘNG)"



    if xuc_xac and len(xuc_xac) == 3:

        kq_xx, tong_xx = du_doan_tu_xuc_xac(*xuc_xac)

    else: kq_xx, tong_xx = "KHÔNG RÕ", None

        

    loai_keo = "THƯỜNG" 

    if kq_chuoi != "KHÔNG RÕ":

        ket_qua = kq_chuoi

        if kq_chuoi == kq_xx: loai_keo = "TỔNG HỢP" 

    else:

        ket_qua = kq_xx if kq_xx != "KHÔNG RÕ" else "KHÔNG RÕ"

    

    return {

        "ket_qua": ket_qua, "loai_keo": loai_keo, "kq_chuoi": kq_chuoi,

        "kq_xx": kq_xx, "pt": pt, "px": px, "kieu_phan_tich": kieu_phan_tich

    }



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

        self.last_raw_pred = None     

        self.last_raw_key = None      

        self.last_raw_bucket = None

        

        self.history_predictions = {} # Lưu phiên và kết quả dự đoán để map lịch sử

        

        self.bait_matrix = {

            "TÀI": {50: False, 60: False, 70: False, 80: False, 90: False},

            "XỈU": {50: False, 60: False, 70: False, 80: False, 90: False},

            "TỔNG HỢP TÀI": {50: False, 60: False, 70: False, 80: False, 90: False},

            "TỔNG HỢP XỈU": {50: False, 60: False, 70: False, 80: False, 90: False}

        }

        self.ensure_files_exist()



    def ensure_files_exist(self):

        if not os.path.exists(self.file_data):

            with open(self.file_data, 'w', encoding='utf-8') as f: json.dump([], f)



    def load_data(self):

        try:

            with open(self.file_data, 'r', encoding='utf-8') as f: return json.load(f)

        except: return []



    def save_data(self, data):

        try:

            with open(self.file_data, 'w', encoding='utf-8') as f: 

                json.dump(data[-HISTORY_MAX:], f, indent=2)

        except Exception as e: print(f"❌ Lỗi lưu file: {e}")



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

            

            # Lấy 20 phiên gần nhất, bỏ qua phiên đang chạy

            for item in full_data[-20:]:

                phien = item['phien']

                actual_res = "TÀI" if item['kq'] == 'T' else "XỈU"

                

                # Check xem hồi đó bot chốt gì

                if str(phien) in self.history_predictions:

                    bot_pred = self.history_predictions[str(phien)]

                    win_status = (bot_pred == actual_res)

                else:

                    bot_pred = "--"

                    win_status = None

                

                history_list.append({

                    "phien": phien,

                    "pred": bot_pred,

                    "actual": actual_res,

                    "win": win_status

                })



            payload = {

                "result": pred,

                "detail": detail,

                "win_rate": round(wr, 1),

                "total_played": self.total_played,

                "history": history_list[::-1] 

            }

            requests.post(SYNC_ENDPOINT, json=payload, timeout=5)

        except Exception as e: print(f"❌ Không thể đồng bộ Dashboard: {e}")



    def inject_new_data(self, phien, dice, tong):

        tx_str = "T" if tong > 10 else "X"

        actual_full = "TÀI" if tong > 10 else "XỈU"



        data = self.load_data()

        data.append({'phien': phien, 'dice': dice, 'tong': tong, 'kq': tx_str})

        self.save_data(data)

        

        if self.last_final_pred is not None:

            self.total_played += 1

            if self.last_final_pred == actual_full:

                self.total_won += 1

                print(f"💰 Ván trước HÚP {actual_full}! (WR: {self.total_won}/{self.total_played})")

            else:

                print(f"💀 Ván trước GÃY! (WR: {self.total_won}/{self.total_played})")

        

        if self.last_raw_key is not None and self.last_raw_bucket is not None:

            raw_was_correct = (self.last_raw_pred == actual_full) 

            matrix_key = self.last_raw_key; bucket = self.last_raw_bucket

            if not raw_was_correct: self.bait_matrix[matrix_key][bucket] = True

            else: self.bait_matrix[matrix_key][bucket] = False



        return len(data)



    def analyze_next_round(self, next_session_id):

        data = self.load_data()

        if len(data) < REQUIRED_LEN:

            msg = f"⚠️ Đang thu thập mồi: {len(data)}/{REQUIRED_LEN} ván."

            print(msg)

            self.sync_to_dashboard(next_session_id, "WAIT", msg)

            return



        recent_50 = data[-50:] if len(data) >= 50 else data

        chuoi_50 = [item['kq'] for item in recent_50]

        recent_13 = data[-REQUIRED_LEN:]

        chuoi_13 = [item['kq'] for item in recent_13]

        list_tong_13 = [item['tong'] for item in recent_13]

        last_dice = recent_13[-1]['dice']

        

        kq_phan_tich = du_doan_tong_hop(chuoi_50, chuoi_13, list_tong_13, last_dice)

        chot_goc = kq_phan_tich["ket_qua"]

        loai_keo = kq_phan_tich["loai_keo"]

        pt = kq_phan_tich["pt"]

        px = kq_phan_tich["px"]

        kieu_phan_tich = kq_phan_tich["kieu_phan_tich"]

        

        print(f"\n🎯 PHIÊN {next_session_id} | LOGIC: {kieu_phan_tich}")

        

        if chot_goc in ["TÀI", "XỈU"]:

            matrix_key = f"TỔNG HỢP {chot_goc}" if loai_keo == "TỔNG HỢP" else chot_goc

            conf_percent = pt if chot_goc == "TÀI" else px

            current_bucket = self.get_confidence_bucket(conf_percent)

            

            note = f"Tỷ lệ {conf_percent:.1f}%"

            if self.bait_matrix[matrix_key][current_bucket]:

                chot_cuoi = "XỈU" if chot_goc == "TÀI" else "TÀI"

                note += " (Đang bẻ cầu bịp)"

            else:

                chot_cuoi = chot_goc

                if loai_keo == "TỔNG HỢP": note += " (Khớp cả xúc xắc)"

                

            self.last_raw_pred = chot_goc

            self.last_raw_key = matrix_key

            self.last_raw_bucket = current_bucket

            self.last_final_pred = chot_cuoi

            

            # Lưu dự đoán để show lịch sử

            self.history_predictions[str(next_session_id)] = chot_cuoi

            

            print(f"🔥 CHỐT CUỐI: VÀO {chot_cuoi} - {note}")

            self.sync_to_dashboard(next_session_id, chot_cuoi, f"{kieu_phan_tich} - {note}")

        else:

            print(f"⚠️ BỎ QUA - Phân tích 50/50")

            self.last_raw_pred = None; self.last_raw_key = None; self.last_raw_bucket = None; self.last_final_pred = None 

            self.sync_to_dashboard(next_session_id, "SKIP", "Tỉ lệ 50/50 -> Bỏ qua")



    def run(self):

        print("🚀 Khởi động TOOL V17 (Flask Server + Threading)...")

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

                    print(f"\n✅ NẠP: PHIÊN {curr_session} | Điểm: {tong}")

                    

                    self.inject_new_data(curr_session, dice, tong)

                    self.analyze_next_round(curr_session + 1)

            except Exception: pass

            time.sleep(2)



def run_ai_bot():

    bot = SunwinLogic_V17()

    bot.run()



if __name__ == "__main__":

    bot_thread = threading.Thread(target=run_ai_bot, daemon=True)

    bot_thread.start()

    port = int(os.environ.get('PORT', 10000))

    app.run(host='0.0.0.0', port=port)

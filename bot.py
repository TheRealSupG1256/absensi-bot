import telebot
import sqlite3
import qrcode
import openpyxl
import os
import io
from datetime import datetime
from telebot import types

TOKEN = os.environ.get("TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))  # Isi ID Telegram kamu

bot = telebot.TeleBot(TOKEN)

# ─── DATABASE ───────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("absensi.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_requests (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            nama TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            nama TEXT,
            role TEXT DEFAULT 'admin'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS murid (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nis TEXT UNIQUE,
            nama TEXT,
            kelas TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS kelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_kelas TEXT UNIQUE,
            qr_token TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS absensi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nis TEXT,
            kelas TEXT,
            tanggal TEXT,
            waktu TEXT,
            status TEXT DEFAULT 'hadir'
        )
    """)
    # Tambah owner sebagai super admin otomatis
    c.execute("""
        INSERT OR IGNORE INTO admins (user_id, username, nama, role)
        VALUES (?, 'owner', 'Owner', 'owner')
    """, (OWNER_ID,))
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect("absensi.db")

# ─── CEK AKSES ───────────────────────────────────────────────────────────────

def is_admin(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def is_owner(user_id):
    return user_id == OWNER_ID

# ─── /start ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def start(msg):
    user_id = msg.from_user.id
    username = msg.from_user.username or "-"
    nama = msg.from_user.first_name or "User"

    if is_admin(user_id):
        kirim_menu_utama(msg)
        return

    # Cek apakah sudah request
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT status FROM admin_requests WHERE user_id=?", (user_id,))
    req = c.fetchone()
    conn.close()

    if req:
        if req[0] == "pending":
            bot.send_message(msg.chat.id, "⏳ Permintaan aksesmu sedang menunggu persetujuan owner.")
        elif req[0] == "rejected":
            bot.send_message(msg.chat.id, "❌ Permintaan aksesmu ditolak. Hubungi owner.")
        return

    # Belum request, suruh request
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📩 Minta Akses", callback_data="minta_akses"))
    bot.send_message(msg.chat.id,
        f"Halo *{nama}*! 👋\n\nKamu belum punya akses ke bot ini.\nKlik tombol di bawah untuk meminta akses ke owner.",
        parse_mode="Markdown", reply_markup=markup)

# ─── REQUEST AKSES ────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "minta_akses")
def minta_akses(call):
    user_id = call.from_user.id
    username = call.from_user.username or "-"
    nama = call.from_user.first_name or "User"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admin_requests (user_id, username, nama, status, created_at) VALUES (?,?,?,'pending',?)",
              (user_id, username, nama, now))
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, "✅ Permintaan terkirim!")
    bot.edit_message_text("⏳ Permintaan aksesmu sudah dikirim ke owner. Tunggu persetujuan ya!",
                          call.message.chat.id, call.message.message_id)

    # Notif ke owner
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ ACC", callback_data=f"acc_{user_id}"),
        types.InlineKeyboardButton("❌ Tolak", callback_data=f"tolak_{user_id}")
    )
    bot.send_message(OWNER_ID,
        f"📩 *Request Akses Baru!*\n\n"
        f"Nama: {nama}\n"
        f"Username: @{username}\n"
        f"ID: `{user_id}`\n"
        f"Waktu: {now}",
        parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("acc_") or c.data.startswith("tolak_"))
def handle_acc_tolak(call):
    if not is_owner(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Bukan hakmu!")
        return

    action, uid = call.data.split("_", 1)
    uid = int(uid)

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, nama FROM admin_requests WHERE user_id=?", (uid,))
    req = c.fetchone()

    if not req:
        bot.answer_callback_query(call.id, "Data tidak ditemukan.")
        conn.close()
        return

    username, nama = req

    if action == "acc":
        c.execute("UPDATE admin_requests SET status='approved' WHERE user_id=?", (uid,))
        c.execute("INSERT OR IGNORE INTO admins (user_id, username, nama, role) VALUES (?,?,?,'admin')",
                  (uid, username, nama))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Di-acc!")
        bot.edit_message_text(f"✅ {nama} sudah di-acc sebagai admin.", call.message.chat.id, call.message.message_id)
        bot.send_message(uid, "✅ Aksesmu sudah di-acc oleh owner! Ketik /start untuk mulai.")
    else:
        c.execute("UPDATE admin_requests SET status='rejected' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "❌ Ditolak.")
        bot.edit_message_text(f"❌ {nama} ditolak.", call.message.chat.id, call.message.message_id)
        bot.send_message(uid, "❌ Maaf, permintaan aksesmu ditolak. Hubungi owner untuk info lebih lanjut.")

# ─── MENU UTAMA ───────────────────────────────────────────────────────────────

def kirim_menu_utama(msg):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👥 Kelola Murid", "🏫 Kelola Kelas")
    markup.row("📊 Lihat Absensi", "📤 Export Excel")
    markup.row("🔑 Kelola Admin" if is_owner(msg.from_user.id) else "ℹ️ Info")
    bot.send_message(msg.chat.id, "✅ Selamat datang di panel admin!\nPilih menu:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Info" and is_admin(m.from_user.id))
def info(msg):
    bot.send_message(msg.chat.id, "Bot Absensi QR — dibuat khusus 🎉\nVersi 1.0")

# ─── KELOLA MURID ─────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "👥 Kelola Murid" and is_admin(m.from_user.id))
def menu_murid(msg):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Tambah Murid", callback_data="tambah_murid"))
    markup.add(types.InlineKeyboardButton("📋 Daftar Murid", callback_data="daftar_murid"))
    markup.add(types.InlineKeyboardButton("🗑 Hapus Murid", callback_data="hapus_murid"))
    bot.send_message(msg.chat.id, "👥 *Kelola Murid*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "tambah_murid")
def tambah_murid(call):
    if not is_admin(call.from_user.id): return
    msg = bot.send_message(call.message.chat.id,
        "📝 Kirim data murid dengan format:\n`NIS|Nama Lengkap|Kelas`\n\nContoh:\n`001|Budi Santoso|10A`",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, proses_tambah_murid)

def proses_tambah_murid(msg):
    try:
        nis, nama, kelas = msg.text.strip().split("|")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO murid (nis, nama, kelas, created_at) VALUES (?,?,?,?)",
                  (nis.strip(), nama.strip(), kelas.strip(), now))
        conn.commit()
        conn.close()
        bot.send_message(msg.chat.id, f"✅ Murid *{nama.strip()}* berhasil ditambahkan!", parse_mode="Markdown")
    except sqlite3.IntegrityError:
        bot.send_message(msg.chat.id, "❌ NIS sudah terdaftar!")
    except:
        bot.send_message(msg.chat.id, "❌ Format salah! Gunakan: `NIS|Nama|Kelas`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "daftar_murid")
def daftar_murid(call):
    if not is_admin(call.from_user.id): return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT nis, nama, kelas FROM murid ORDER BY kelas, nama")
    murid_list = c.fetchall()
    conn.close()

    if not murid_list:
        bot.send_message(call.message.chat.id, "📋 Belum ada murid terdaftar.")
        return

    teks = "📋 *Daftar Murid:*\n\n"
    for nis, nama, kelas in murid_list:
        teks += f"• [{kelas}] {nama} — `{nis}`\n"
    bot.send_message(call.message.chat.id, teks, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "hapus_murid")
def hapus_murid(call):
    if not is_admin(call.from_user.id): return
    msg = bot.send_message(call.message.chat.id, "🗑 Kirim NIS murid yang mau dihapus:")
    bot.register_next_step_handler(msg, proses_hapus_murid)

def proses_hapus_murid(msg):
    nis = msg.text.strip()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT nama FROM murid WHERE nis=?", (nis,))
    murid = c.fetchone()
    if not murid:
        bot.send_message(msg.chat.id, "❌ NIS tidak ditemukan!")
        conn.close()
        return
    c.execute("DELETE FROM murid WHERE nis=?", (nis,))
    conn.commit()
    conn.close()
    bot.send_message(msg.chat.id, f"✅ Murid *{murid[0]}* berhasil dihapus.", parse_mode="Markdown")

# ─── KELOLA KELAS & QR ────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🏫 Kelola Kelas" and is_admin(m.from_user.id))
def menu_kelas(msg):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Tambah Kelas + Buat QR", callback_data="tambah_kelas"))
    markup.add(types.InlineKeyboardButton("📋 Daftar Kelas & QR", callback_data="daftar_kelas"))
    bot.send_message(msg.chat.id, "🏫 *Kelola Kelas*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "tambah_kelas")
def tambah_kelas(call):
    if not is_admin(call.from_user.id): return
    msg = bot.send_message(call.message.chat.id, "📝 Kirim nama kelas (contoh: `10A`):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, proses_tambah_kelas)

def proses_tambah_kelas(msg):
    nama_kelas = msg.text.strip().upper()
    import uuid
    token = str(uuid.uuid4())[:8].upper()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO kelas (nama_kelas, qr_token, created_at) VALUES (?,?,?)",
                  (nama_kelas, token, now))
        conn.commit()
    except sqlite3.IntegrityError:
        bot.send_message(msg.chat.id, "❌ Kelas sudah ada!")
        conn.close()
        return
    conn.close()

    # Generate QR
    qr_data = f"ABSEN|{nama_kelas}|{token}"
    qr = qrcode.make(qr_data)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)

    bot.send_photo(msg.chat.id, buf,
        caption=f"✅ Kelas *{nama_kelas}* dibuat!\n📌 Token: `{token}`\n\nSimpan QR ini untuk absensi.",
        parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "daftar_kelas")
def daftar_kelas(call):
    if not is_admin(call.from_user.id): return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT nama_kelas, qr_token FROM kelas ORDER BY nama_kelas")
    kelas_list = c.fetchall()
    conn.close()

    if not kelas_list:
        bot.send_message(call.message.chat.id, "📋 Belum ada kelas.")
        return

    for nama_kelas, token in kelas_list:
        qr_data = f"ABSEN|{nama_kelas}|{token}"
        qr = qrcode.make(qr_data)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        bot.send_photo(call.message.chat.id, buf,
            caption=f"🏫 *{nama_kelas}*\n📌 Token: `{token}`",
            parse_mode="Markdown")

# ─── LIHAT ABSENSI ────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "📊 Lihat Absensi" and is_admin(m.from_user.id))
def lihat_absensi(msg):
    msg2 = bot.send_message(msg.chat.id,
        "📊 Ketik nama kelas yang ingin dilihat absensinya (contoh: `10A`):\nAtau ketik `semua` untuk lihat semua.",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg2, proses_lihat_absensi)

def proses_lihat_absensi(msg):
    kelas = msg.text.strip().upper()
    conn = get_conn()
    c = conn.cursor()

    if kelas == "SEMUA":
        c.execute("""
            SELECT a.nis, m.nama, a.kelas, a.tanggal, a.waktu
            FROM absensi a LEFT JOIN murid m ON a.nis=m.nis
            ORDER BY a.tanggal DESC, a.waktu DESC LIMIT 50
        """)
    else:
        c.execute("""
            SELECT a.nis, m.nama, a.kelas, a.tanggal, a.waktu
            FROM absensi a LEFT JOIN murid m ON a.nis=m.nis
            WHERE a.kelas=?
            ORDER BY a.tanggal DESC, a.waktu DESC LIMIT 50
        """, (kelas,))

    data = c.fetchall()
    conn.close()

    if not data:
        bot.send_message(msg.chat.id, "📭 Belum ada data absensi.")
        return

    teks = f"📊 *Absensi {kelas}* (50 terbaru):\n\n"
    for nis, nama, kls, tgl, wkt in data:
        teks += f"• {nama or nis} — {kls} — {tgl} {wkt}\n"

    bot.send_message(msg.chat.id, teks, parse_mode="Markdown")

# ─── EXPORT EXCEL ─────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "📤 Export Excel" and is_admin(m.from_user.id))
def export_excel(msg):
    msg2 = bot.send_message(msg.chat.id,
        "📤 Ketik bulan dan tahun yang ingin di-export:\nFormat: `MM-YYYY`\nContoh: `11-2026`",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg2, proses_export_excel)

def proses_export_excel(msg):
    try:
        bulan_tahun = msg.text.strip()
        bulan, tahun = bulan_tahun.split("-")
        bulan = bulan.zfill(2)

        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT a.nis, m.nama, a.kelas, a.tanggal, a.waktu, a.status
            FROM absensi a LEFT JOIN murid m ON a.nis=m.nis
            WHERE strftime('%m', a.tanggal)=? AND strftime('%Y', a.tanggal)=?
            ORDER BY a.kelas, a.tanggal, a.waktu
        """, (bulan, tahun))
        data = c.fetchall()
        conn.close()

        if not data:
            bot.send_message(msg.chat.id, f"📭 Tidak ada data absensi untuk {bulan}-{tahun}.")
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Absensi {bulan}-{tahun}"
        ws.append(["No", "NIS", "Nama", "Kelas", "Tanggal", "Waktu", "Status"])

        for i, (nis, nama, kelas, tgl, wkt, status) in enumerate(data, 1):
            ws.append([i, nis, nama or "-", kelas, tgl, wkt, status])

        # Style header
        from openpyxl.styles import Font, PatternFill
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="4472C4")
            cell.font = Font(bold=True, color="FFFFFF")

        # Auto width
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = max_len + 4

        filename = f"/tmp/absensi_{bulan}_{tahun}.xlsx"
        wb.save(filename)

        with open(filename, "rb") as f:
            bot.send_document(msg.chat.id, f,
                caption=f"📊 Export absensi bulan {bulan}-{tahun} ✅",
                visible_file_name=f"Absensi_{bulan}_{tahun}.xlsx")

        os.remove(filename)

    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Gagal export: {e}\nPastikan format `MM-YYYY`", parse_mode="Markdown")

# ─── KELOLA ADMIN (OWNER ONLY) ────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🔑 Kelola Admin" and is_owner(m.from_user.id))
def kelola_admin(msg):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 Daftar Admin", callback_data="daftar_admin"))
    markup.add(types.InlineKeyboardButton("🗑 Hapus Admin", callback_data="hapus_admin"))
    markup.add(types.InlineKeyboardButton("📩 Request Pending", callback_data="request_pending"))
    bot.send_message(msg.chat.id, "🔑 *Kelola Admin*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "daftar_admin")
def daftar_admin(call):
    if not is_owner(call.from_user.id): return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, nama, role FROM admins")
    admins = c.fetchall()
    conn.close()

    teks = "👥 *Daftar Admin:*\n\n"
    for uid, uname, nama, role in admins:
        teks += f"• {nama} (@{uname}) — `{role}`\n  ID: `{uid}`\n\n"
    bot.send_message(call.message.chat.id, teks, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "hapus_admin")
def hapus_admin_cb(call):
    if not is_owner(call.from_user.id): return
    msg = bot.send_message(call.message.chat.id, "🗑 Kirim ID Telegram admin yang mau dihapus:")
    bot.register_next_step_handler(msg, proses_hapus_admin)

def proses_hapus_admin(msg):
    try:
        uid = int(msg.text.strip())
        if uid == OWNER_ID:
            bot.send_message(msg.chat.id, "❌ Tidak bisa hapus dirimu sendiri!")
            return
        conn = get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.send_message(msg.chat.id, f"✅ Admin dengan ID `{uid}` dihapus.", parse_mode="Markdown")
    except:
        bot.send_message(msg.chat.id, "❌ ID tidak valid.")

@bot.callback_query_handler(func=lambda c: c.data == "request_pending")
def request_pending(call):
    if not is_owner(call.from_user.id): return
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, nama, created_at FROM admin_requests WHERE status='pending'")
    reqs = c.fetchall()
    conn.close()

    if not reqs:
        bot.send_message(call.message.chat.id, "📭 Tidak ada request pending.")
        return

    for uid, uname, nama, created in reqs:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ ACC", callback_data=f"acc_{uid}"),
            types.InlineKeyboardButton("❌ Tolak", callback_data=f"tolak_{uid}")
        )
        bot.send_message(call.message.chat.id,
            f"📩 *Request:*\nNama: {nama}\nUsername: @{uname}\nID: `{uid}`\nWaktu: {created}",
            parse_mode="Markdown", reply_markup=markup)

# ─── JALANKAN BOT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("Bot berjalan...")
    bot.infinity_polling()

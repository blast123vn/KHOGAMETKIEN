# GAMEVAULT Secure — SQLite local / PostgreSQL production

GAMEVAULT giữ SQLite cho chạy thử trên máy cá nhân, và tự dùng PostgreSQL khi biến môi trường `DATABASE_URL` được cấu hình. Không cần sửa các truy vấn API hiện có.

## Ưu tiên miễn phí: Render Free + PostgreSQL miễn phí bên ngoài

Render Web Service Free không có ổ đĩa bền vững; vì vậy **không dùng SQLite làm database production trên Render Free**. Cách này dùng một nhà cung cấp PostgreSQL có gói miễn phí (ví dụ Neon hoặc Supabase), rồi kết nối bằng `DATABASE_URL`. Gói miễn phí, giới hạn lưu trữ, chính sách ngủ/ngưng hoặc thời hạn có thể thay đổi; hãy kiểm tra điều khoản hiện tại của nhà cung cấp trước khi đưa dữ liệu thật lên.

### 1. Tạo PostgreSQL

1. Tạo project PostgreSQL ở nhà cung cấp bạn chọn.
2. Lấy connection string/URL dành cho ứng dụng. Giữ URL riêng tư; không gửi vào chat, không commit vào GitHub.
3. Nếu nhà cung cấp yêu cầu SSL, dùng URL có `sslmode=require` (thường URL được cấp đã bao gồm).

### 2. Sao lưu SQLite trước khi chuyển

Dừng ứng dụng đang ghi dữ liệu trước khi tạo bản sao lưu.

```bash
# macOS/Linux, từ thư mục GAMEVAULT_secure
cp backend/gamevault.db backend/gamevault.backup.db
```

PowerShell trên Windows:

```powershell
Copy-Item .\backend\gamevault.db .\backend\gamevault.backup.db
```

Nếu `GAMEVAULT_DB` đang trỏ đến vị trí khác, hãy sao lưu đúng file đó. Giữ bản sao lưu ngoài thư mục Git hoặc kiểm tra `.gitignore` để chắc chắn file `.db` không bị đẩy lên GitHub. Không xóa bản SQLite gốc cho đến khi kiểm tra xong dữ liệu trên PostgreSQL.

### 3. Cài thư viện và chạy công cụ chuyển dữ liệu

Chạy trên máy cá nhân trong môi trường Python của dự án; cần cài dependencies trước:

```bash
pip install -r requirements.txt
```

Linux/macOS:

```bash
export SQLITE_SOURCE="$PWD/backend/gamevault.backup.db"
export DATABASE_URL='DAN_URL_POSTGRESQL_CUA_BAN'
python migrate_sqlite_to_postgres.py
```

Windows PowerShell:

```powershell
$env:SQLITE_SOURCE = (Resolve-Path .\backend\gamevault.backup.db).Path
$env:DATABASE_URL = 'DAN_URL_POSTGRESQL_CUA_BAN'
python .\migrate_sqlite_to_postgres.py
```

**Chỉ chạy công cụ trên database PostgreSQL trống.** Công cụ dừng nếu thấy bảng đích đã có dữ liệu; nó không xóa hoặc ghi đè dữ liệu hiện có. Khi hoàn tất, công cụ in số dòng của từng bảng và so sánh với SQLite.

### 4. Cấu hình Render

1. Đẩy mã nguồn đã sửa lên GitHub, nhưng **không đẩy** `.env`, file `.db`, file backup hoặc URL database.
2. Trong Render chọn **New → Blueprint** và chọn repository có `render.yaml`.
3. Điền các biến môi trường được đánh dấu `sync: false`:
   - `DATABASE_URL`: URL PostgreSQL ở bước 1.
   - `ADMIN_USERNAME`: tên Admin ban đầu.
   - `ADMIN_PASSWORD`: mật khẩu Admin mạnh, dài và duy nhất.
   - `ADMIN_REVEAL_CODE`: mã xác nhận riêng, khác mật khẩu Admin.
   - `GAME_PASSWORD_KEY`: Fernet key giữ nguyên từ hệ thống cũ nếu cần đọc lại mật khẩu game đã mã hóa.
4. `SESSION_SECRET` được Render tự tạo; `COOKIE_SECURE=1` bật cookie an toàn qua HTTPS.
5. Deploy và kiểm tra đăng nhập, thành viên, tài khoản game, chat và yêu cầu mật khẩu. Không tạo lại Admin nếu bảng `users` đã có dữ liệu.

`render.yaml` dùng Web Service Free, không gắn Persistent Disk và không đặt `GAMEVAULT_DB`; khi `DATABASE_URL` có giá trị, backend chọn PostgreSQL.

### 5. Bảo vệ mật khẩu và khóa

- `password_hash` là mật khẩu đăng nhập người dùng đã được hash bằng Werkzeug; không chuyển thành mật khẩu dạng rõ.
- `accounts.password_enc` là mật khẩu game mã hóa bằng Fernet. **Giữ nguyên `GAME_PASSWORD_KEY` cũ** khi chuyển database. Nếu mất hoặc đổi khóa, dữ liệu mật khẩu game đã mã hóa có thể không giải mã được.
- Không đưa `DATABASE_URL`, `ADMIN_PASSWORD`, `ADMIN_REVEAL_CODE`, `SESSION_SECRET` hoặc `GAME_PASSWORD_KEY` vào mã nguồn, ảnh chụp, chat công khai hay GitHub. Chỉ đặt chúng trong Render Environment hoặc biến môi trường cục bộ.
- Không dùng lại mật khẩu đang dùng ở email, mạng xã hội hoặc dịch vụ khác. Hạn chế quyền truy cập database và bật xác thực hai lớp cho tài khoản nhà cung cấp nếu có.
- Tạo bản sao lưu PostgreSQL định kỳ và lưu ở nơi riêng biệt; gói miễn phí có thể không bao gồm backup tự động hoặc phục hồi theo thời điểm.
- Khi database đã chuyển và kiểm chứng đủ dữ liệu, giữ file backup SQLite ngoại tuyến thêm một thời gian trước khi quyết định xóa.

## Chạy local

Nếu không đặt `DATABASE_URL`, ứng dụng vẫn dùng SQLite ở `backend/gamevault.db` như trước. Sao chép `.env.example` thành `.env` và thay tất cả giá trị mẫu bằng secret thật, sau đó chạy:

```bash
python backend/server.py
```

Mở `http://127.0.0.1:5000`. Không commit `.env` hoặc database lên GitHub.

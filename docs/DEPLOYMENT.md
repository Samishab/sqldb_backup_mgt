# النشر على جهاز النسخ الاحتياطي (Windows Server) – خلاصة التجربة

البنية المعتمدة: **اللوحة على جهاز النسخ**، تتصل بالسيرفر الرئيسي عبر SQL، و`BACKUP` يكتب مباشرة على مشاركة في جهاز النسخ.

```
جهاز النسخ (BackupHub + مجلد مشترك)  <--- SQL (1433) --->  السيرفر الرئيسي (SQL Server)
        \Salam_AutoBU\BackupVault  <------ BACKUP TO DISK -------+
```

> أمر `BACKUP` ينفَّذ من SQL Server نفسه، فالمسار يُفهم من جهة السيرفر الرئيسي: **استخدم مسار UNC** وليس `D:\...` المحلي.

## 1) جهاز النسخ: المجلد المشترك والمستخدم
```powershell
# مجلد D:\BackupVault مشارك باسم BackupVault
$pw = Read-Host -AsSecureString "كلمة مرور sqlbackup"
New-LocalUser sqlbackup -Password $pw -PasswordNeverExpires -UserMayNotChangePassword
icacls D:\BackupVault /grant "sqlbackup:(OI)(CI)M"
Grant-SmbShareAccess -Name BackupVault -AccountName sqlbackup -AccessRight Change -Force
Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"
```

## 2) السيرفر الرئيسي (Workgroup): حساب خدمة SQL Server
في Workgroup لا يقدر `NT SERVICE\MSSQLSERVER` على الدخول لمشاركة جهاز آخر (الخطأ 5: Access denied).
الحل: مستخدم محلي بنفس الاسم وكلمة المرور على الجهازين، وتشغيل خدمة SQL به:
1. إنشاء المستخدم المحلي `sqlbackup` على الرئيسي بنفس كلمة المرور.
2. **SQL Server Configuration Manager** (`SQLServerManager15.msc` لـ 2019) ← SQL Server Services ← Properties ← Log On ← This account ← `.\sqlbackup`.
3. ⚠️ يعيد تشغيل SQL Server (توقف ~دقيقة): نفّذه خارج الدوام. للتراجع: Built-in account ← `NT Service\MSSQLSERVER`.

اختبار: من SSMS على الرئيسي
```sql
BACKUP DATABASE [DbName] TO DISK = N'\Salam_AutoBU\BackupVault\test.bak' WITH INIT, CHECKSUM;
```
أخطاء شائعة: `53` = الاسم/الشبكة (جرّب IP)، `5` = الصلاحيات.

## 3) مستخدم SQL للوحة بأقل صلاحيات
```sql
USE master;
CREATE LOGIN backup_app WITH PASSWORD = N'...', CHECK_POLICY = ON;
GRANT VIEW ANY DEFINITION TO backup_app;      -- عرض القواعد
ALTER SERVER ROLE dbcreator ADD MEMBER backup_app;  -- VERIFYONLY والاسترجاع
GO
USE [DbName];
CREATE USER backup_app FOR LOGIN backup_app;
ALTER ROLE db_backupoperator ADD MEMBER backup_app;
```
في اللوحة: الاتصالات ← **SQL Login** (Windows Authentication يدخل بحساب ويندوز الذي تعمل به اللوحة وليس بهذا المستخدم).
`DBCC CHECKDB` في «اختبار الاسترجاع» يحتاج مالك القاعدة؛ إن لم تتوفر الصلاحية يُسجَّل تحذير ويُحذف الاسترجاع التجريبي دائمًا.

## 4) تثبيت اللوحة
- Python **3.12 أو 3.13 لكل المستخدمين** (`InstallAllUsers=1` → `C:\Program Files\Python312`)، لأن بايثون المثبّت داخل مجلد مستخدم لا تصل له خدمة تعمل بحساب آخر.
- ```
  git clone <repo> D:\DB_BU_CP
  cd /d D:\DB_BU_CP
  "C:\Program Files\Python312\python.exe" -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  ```
- الإعدادات ← **المجلد المحلي الأساسي** = `\Salam_AutoBU\BackupVault` (UNC!) ثم «حفظ الإعدادات».

## 5) التشغيل كخدمة ويندوز (NSSM)
```
nssm install BackupHub "D:\DB_BU_CP\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 8765"
nssm set BackupHub AppDirectory D:\DB_BU_CP
nssm set BackupHub Start SERVICE_AUTO_START
nssm set BackupHub AppStdout D:\DB_BU_CP\data\service.log
nssm set BackupHub AppStderr D:\DB_BU_CP\data\service.log
icacls D:\DB_BU_CP /grant "sqlbackup:(OI)(CI)M"
icacls "C:\Program Files\Python312" /grant "sqlbackup:(OI)(CI)RX"
```
ثم `services.msc` ← BackupHub ← Log On ← `.\sqlbackup`، ثم `nssm start BackupHub`. للوصول من أجهزة الشبكة افتح المنفذ 8765 في الجدار.
الجداول الفائتة أثناء الإيقاف تُنفَّذ عند الإقلاع إذا لم يمرّ أكثر من ساعة.

## ملاحظات تشغيلية
- **Recovery Model:** نسخ السجل يتطلب `FULL` (يرفضه `SIMPLE` بالخطأ 4208). عند التحويل خذ نسخة كاملة أولًا، وجدول Log بانتظام وإلا يكبر ملف `.ldf`.
- **الضغط:** غير مدعوم في Express؛ في Standard/Enterprise غالبًا 3–8× (مثال: 3.7 GB → 622 MB).
- **التفاضلية** تحتاج الكاملة التي قبلها؛ اجعل احتفاظ الكاملة أطول من التفاضلية.
- **Python 3.15** غير مناسب (لا wheels لـ pyodbc) → استخدم 3.12/3.13.
- منفذ 8080 قد يكون محظورًا في ويندوز؛ المستخدم 8765.

## نمط الجدولة الموصى به (سلاسل أسبوعية)
| الجدول | النوع | التوقيت | الاحتفاظ |
|---|---|---|---|
| Full أسبوعي | كاملة | أسبوعي، يوم + وقت هادئ | **سلاسل = 2** (يحذف الأقدم مع سلاسلها عند ظهور Full جديد) |
| Differential يومي | تفاضلية | يوميًا أو كل عدة ساعات | كل القيم 0 (تُحذف مع سلسلتها) |
| Log | سجل العمليات | Cron مثل `* 7-20 * * *` (كل دقيقة من 7ص حتى 8:59م) | كل القيم 0 |

- **لا تجعل التفاضلية كل دقيقة:** حجم التفاضلية يكبر يوميًا لأنها تحمل كل التغييرات منذ آخر Full، فتتكدس مئات الجيجات. نسخ **السجل** (Log) كل دقيقة صغيرة جدًا وتعطي استرجاعًا لأي لحظة، لكنها تتطلب Recovery Model = FULL.
- أوقف «التحقق» في الجداول عالية التكرار (Log/Diff كل دقيقة) لأنه يقرأ الملف كاملًا في كل مرة.
- مثال Cron: كل دقيقة 7ص–9م: `* 7-20 * * *` ثم أضف جدولًا ثانيًا `0 21 * * *` لنسخة الساعة 9م.
- الاحتفاظ بالسلاسل يُطبَّق عند نجاح نسخة Full: يُبقي آخر N نسخ كاملة وكل ما بعد أقدمها، ويحذف ما قبلها.

## التحديث من GitHub
أول مرة على جهاز يحتوي المشروع (منسوخًا يدويًا) دون حذف `data` و`.venv` (مستثنيان من Git):
```
cd /d D:\DB_BU_CP
git init -b main
git remote add origin https://github.com/Samishab/sqldb_backup_mgt.git
git fetch origin
git reset --hard origin/main
.venv\Scripts\python.exe -m pip install -r requirements.txt
nssm restart BackupHub
```
لأي تحديث لاحق:
```
cd /d D:\DB_BU_CP
git pull
nssm restart BackupHub
```
إذا ظهر `dubious ownership`: `git config --global --add safe.directory D:/DB_BU_CP`. ويحتاج الجهاز إلى Git (https://git-scm.com/download/win)،
أو نزّل ZIP من صفحة المستودع (Code ← Download ZIP) وانسخ مجلد `app` فوق القديم.

## تغيير Recovery Model إلى FULL
`ALTER DATABASE ... SET RECOVERY FULL` تغيير فوري ولا يوقف القاعدة ولا يقطع الاتصالات ولا يحتاج إعادة تشغيل. لكن:
- لا تبدأ سلسلة السجل إلا بعد أول **نسخة Full** بعد التحويل.
- بدون نسخ Log منتظم يكبر ملف `.ldf` بلا حد.
- إذا كان عند الجهة برنامج نسخ آخر: نسخ Full غير `COPY_ONLY` تعيد قاعدة التفاضلي، ونسخ Log من أكثر من أداة تشتّت السلسلة (يلزم كل الملفات للاسترجاع). اجعل أداة واحدة فقط مسؤولة عن نسخ Log.

## المتبقي / أفكار
- الرفع على Google Drive عبر rclone (وجهة من نوع rclone؛ للتشفير استخدم remote من نوع crypt).
- اختيار اتصال آخر هدفًا للاسترجاع (لاختبار الاسترجاع على SQL Server في جهاز النسخ بدل الإنتاج).
- تنبيه إذا توقفت اللوحة نفسها (مراقبة خارجية).

## نسخ Full من أداة أخرى (خطأ 3136)
أي نسخة Full غير `COPY_ONLY` على القاعدة (برنامج المنشأة نفسه، أو SSMS) تصبح أساس كل التفاضليات بعدها، فلا تُستعاد من ملفات اللوحة وحدها (الخطأ 3136).
- الاسترجاع يقرأ `RESTORE HEADERONLY` ويطابق `DifferentialBaseGUID` بـ `BackupSetGUID` لاختيار الـ Full الصحيح.
- الإعدادات ← «حوّل التفاضلية تلقائيًا إلى Full…» (مفعّل افتراضيًا): قبل كل تفاضلية تفحص اللوحة `msdb.dbo.backupset`، وإن كان آخر Full من خارجها أخذت Full بدلًا منها. يحتاج `backup_app` قراءة msdb:
  ```sql
  USE msdb;
  CREATE USER backup_app FOR LOGIN backup_app;
  GRANT SELECT ON dbo.backupset TO backup_app;
  GRANT SELECT ON dbo.backupmediafamily TO backup_app;
  ```
  وإن لم تتوفر الصلاحية يُسجَّل تحذير وتستمر النسخة كتفاضلية.
- الأمتن: نسخ **Log** (Recovery FULL) لأن Full الغريب لا يكسر سلسلة السجل (ما لم تأخذ الأداة الأخرى نسخ Log أيضًا).

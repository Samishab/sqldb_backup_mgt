# BackupHub – لوحة التحكم بالنسخ الاحتياطي لـ SQL Server

لوحة ويب خفيفة (FastAPI + SQLite + APScheduler، واجهة عربية RTL) تتحكم بالنسخ الاحتياطي لقواعد SQL Server
من جهاز مستقل، مع جدولة وسجل وسياسة احتفاظ واسترجاع وتنبيهات. تدعم أيضًا SQLite وMySQL وPostgreSQL (نسخ كامل فقط).

## الميزات
- **SQL Server:** `BACKUP ... WITH COMPRESSION, CHECKSUM` (كاملة / تفاضلية / سجل عمليات)، مع الرجوع تلقائيًا لبدون ضغط إذا كان الإصدار (Express) لا يدعمه.
- **التحقق:** `RESTORE VERIFYONLY` بعد كل نسخة.
- **الجدولة:** كل فترة، يومي، أسبوعي، شهري، أو Cron. تشغيل فوري بزر «انسخ الآن».
- **الاحتفاظ (GFS):** يومي / أسبوعي / شهري لكل جدول؛ للسجل بعدد الأيام. تُحفظ آخر نسخة دائمًا.
- **الوجهات:** المجلد الأساسي + وجهات إضافية (مجلد / شبكة UNC / rclone لـ Google Drive وغيره).
- **الاسترجاع:** دائمًا كقاعدة **جديدة** (لا يكتب فوق الأصلية)، ويبني السلسلة تلقائيًا (كاملة ← تفاضلية ← سجلات). و«اختبار استرجاع» يسترجع ثم يحذف.
- **التنبيهات:** Telegram / SMTP / Webhook عند الفشل، وتنبيه إذا مرّ وقت طويل بدون نسخة ناجحة.
- سجل تدقيق، وتسجيل دخول بكلمة مرور (تُعيَّن في أول تشغيل).

## التشغيل السريع
```
run.bat
```
ثم افتح `http://localhost:8765` وعيّن كلمة المرور. يحتاج Python **3.12 أو 3.13** (الإصدارات الأحدث ليس لها حزم جاهزة لـ pyodbc)
و ODBC Driver لـ SQL Server. تفاصيل النشر الكاملة في [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## تشغيل اللوحة كخدمة ويندوز (تعمل بعد إعادة التشغيل)
باستخدام [NSSM](https://nssm.cc/download) (ضع `nssm.exe` في `tools\`):
```
nssm install BackupHub "D:\DB_BU_CP\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 8765"
nssm set BackupHub AppDirectory D:\DB_BU_CP
nssm set BackupHub Start SERVICE_AUTO_START
nssm set BackupHub AppStdout D:\DB_BU_CP\data\service.log
nssm set BackupHub AppStderr D:\DB_BU_CP\data\service.log
nssm start BackupHub
```
ثم من `services.msc` ← BackupHub ← Log On اختر الحساب الذي يملك صلاحية على مجلد المشروع ومجلد النسخ.
التفاصيل والأخطاء الشائعة في [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). لإيقافها/حذفها: `nssm stop BackupHub` / `nssm remove BackupHub confirm`.

## تجربة بدون قاعدة حقيقية
- `setup_demo.py`: ينشئ قاعدة `DemoShop` على `localhost\SQLEXPRESS` + اتصال + 3 جداول سريعة للتجربة.
- `demo_activity.py`: يضيف صفوفًا كل 10 ثوانٍ ليكون للتفاضلي والسجل ما ينسخانه.
- `make_demo_db.py`: قاعدة SQLite تجريبية.

## هيكل المشروع
```
app/main.py       واجهة API والمصادقة
app/engine.py     النسخ، التحقق، الرفع، الاحتفاظ، الاسترجاع
app/scheduler.py  الجدولة (APScheduler) ومراقبة التأخر
app/alerts.py     Telegram / SMTP / Webhook
app/db.py         تخزين الإعدادات والسجل (data/controlpanel.db)
app/static/       الواجهة (HTML/CSS/JS بدون بناء)
```

## ملاحظات أمنية
- `data/controlpanel.db` يحوي كلمات مرور الاتصالات بنص واضح: لا تنشره ولا تضعه في Git (مستثنى في `.gitignore`).
- لا تعرّض اللوحة للإنترنت؛ اجعلها على الشبكة المحلية أو خلف VPN.
- للاتصال بالسيرفر استخدم مستخدم SQL بأقل صلاحيات (انظر النشر).

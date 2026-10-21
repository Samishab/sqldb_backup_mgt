# أدوات خارجية (Windows x64)

ملفات تنفيذية جاهزة حتى تكتمل النسخة بدون تنزيل. تحقق من البصمة قبل الاستخدام، ويُفضَّل مقارنتها بنسخة رسمية.

| الملف | الإصدار | المصدر | الترخيص | SHA-256 |
|---|---|---|---|---|
| `nssm.exe` | 2.24 (2014) | https://nssm.cc/download | Public domain | `f689ee9af94b00e9e3f0bb072b34caaf207f32dcb4f5782fc9ca351df9a06c97` |
| `rclone/rclone.exe` | v1.75.2 | https://rclone.org/downloads/ | MIT | `41eab3e118d264920b62c3327966c5ece0dc4dd715ee617d9e30450d8ead95a4` |

التحقق (PowerShell): `Get-FileHash tools\rclone\rclone.exe -Algorithm SHA256`

- `nssm.exe` يحوّل اللوحة إلى خدمة ويندوز (انظر README الرئيسي).
- `rclone.exe` يرفع النسخ إلى السحابة. ملف إعداداته `data\rclone.conf` **لا يُرفع** إلى Git.
- حجم `rclone.exe` قريب من حد GitHub (100MB). إن تجاوزه إصدار مستقبلي فاستخدم GitHub Releases بدل Git.

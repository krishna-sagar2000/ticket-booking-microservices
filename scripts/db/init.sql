-- Local development only. Fake passwords. One database + one user per service.
CREATE DATABASE IF NOT EXISTS booking_db;
CREATE USER IF NOT EXISTS 'booking_user'@'%' IDENTIFIED BY 'booking_pass';
GRANT ALL PRIVILEGES ON booking_db.* TO 'booking_user'@'%';

CREATE DATABASE IF NOT EXISTS seat_db;
CREATE USER IF NOT EXISTS 'seat_user'@'%' IDENTIFIED BY 'seat_pass';
GRANT ALL PRIVILEGES ON seat_db.* TO 'seat_user'@'%';

CREATE DATABASE IF NOT EXISTS payment_db;
CREATE USER IF NOT EXISTS 'payment_user'@'%' IDENTIFIED BY 'payment_pass';
GRANT ALL PRIVILEGES ON payment_db.* TO 'payment_user'@'%';

CREATE DATABASE IF NOT EXISTS notification_db;
CREATE USER IF NOT EXISTS 'notification_user'@'%' IDENTIFIED BY 'notification_pass';
GRANT ALL PRIVILEGES ON notification_db.* TO 'notification_user'@'%';

FLUSH PRIVILEGES;

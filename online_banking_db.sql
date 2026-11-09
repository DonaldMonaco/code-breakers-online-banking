-- =====================================================================
-- CSC 430 - Lab 4: Online Banking Database (physical data model)
-- Team: Code Breakers
-- DBMS: MySQL 8.0+  (InnoDB, utf8mb4)
-- =====================================================================

DROP DATABASE IF EXISTS online_banking;
CREATE DATABASE online_banking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE online_banking;

-- ---------------------------------------------------------------------
-- 1. CUSTOMER
-- ---------------------------------------------------------------------
CREATE TABLE customer (
    customer_id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    first_name       VARCHAR(50)   NOT NULL,
    last_name        VARCHAR(50)   NOT NULL,
    email            VARCHAR(100)  NOT NULL,
    phone            VARCHAR(20)   NOT NULL,           -- receives one-time codes
    username         VARCHAR(30)   NOT NULL,
    password_hash    VARCHAR(255)  NOT NULL,           -- salted adaptive hash, never plain text
    failed_attempts  TINYINT UNSIGNED NOT NULL DEFAULT 0,
    locked_until     DATETIME      NULL,               -- set after 5 failed attempts (15 min)
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_customer PRIMARY KEY (customer_id),
    CONSTRAINT uq_customer_username UNIQUE (username),
    CONSTRAINT uq_customer_email    UNIQUE (email),
    CONSTRAINT ck_customer_attempts CHECK (failed_attempts <= 5)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 2. ACCOUNT   (Customer 1 --- owns --- N Account)
-- ---------------------------------------------------------------------
CREATE TABLE account (
    account_no         CHAR(10)      NOT NULL,
    customer_id        INT UNSIGNED  NOT NULL,
    account_type       VARCHAR(10)   NOT NULL,
    available_balance  DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    status             VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE',
    opened_date        DATE          NOT NULL,
    CONSTRAINT pk_account PRIMARY KEY (account_no),
    CONSTRAINT fk_account_customer FOREIGN KEY (customer_id)
        REFERENCES customer (customer_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_account_type    CHECK (account_type IN ('CHECKING', 'SAVINGS')),
    CONSTRAINT ck_account_status  CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    CONSTRAINT ck_account_balance CHECK (available_balance >= 0)
) ENGINE = InnoDB;

CREATE INDEX ix_account_customer ON account (customer_id);

-- ---------------------------------------------------------------------
-- 3. TRANSFER  (Account 1 --- source --- N Transfer,
--               Account 1 --- destination --- N Transfer)
-- ---------------------------------------------------------------------
CREATE TABLE transfer (
    transfer_id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    reference_no     CHAR(9)       NOT NULL,           -- shown on receipt, e.g. TRF000123
    request_id       CHAR(36)      NOT NULL,           -- client UUID; blocks double submits
    source_acct_no   CHAR(10)      NOT NULL,
    dest_acct_no     CHAR(10)      NOT NULL,
    amount           DECIMAL(12,2) NOT NULL,
    status           VARCHAR(10)   NOT NULL DEFAULT 'PENDING',
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at     DATETIME      NULL,
    CONSTRAINT pk_transfer PRIMARY KEY (transfer_id),
    CONSTRAINT uq_transfer_reference UNIQUE (reference_no),
    CONSTRAINT uq_transfer_request   UNIQUE (request_id),
    CONSTRAINT fk_transfer_source FOREIGN KEY (source_acct_no)
        REFERENCES account (account_no) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_transfer_dest   FOREIGN KEY (dest_acct_no)
        REFERENCES account (account_no) ON UPDATE RESTRICT ON DELETE RESTRICT,
    -- (MySQL forbids CHECKs on columns with cascading FK actions, so these use RESTRICT)
    CONSTRAINT ck_transfer_amount   CHECK (amount > 0),
    CONSTRAINT ck_transfer_accounts CHECK (source_acct_no <> dest_acct_no),
    CONSTRAINT ck_transfer_status   CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED'))
) ENGINE = InnoDB;

CREATE INDEX ix_transfer_source  ON transfer (source_acct_no, created_at);
CREATE INDEX ix_transfer_dest    ON transfer (dest_acct_no, created_at);
CREATE INDEX ix_transfer_created ON transfer (created_at);

-- ---------------------------------------------------------------------
-- 4. ACCOUNT_TRANSACTION  (Account 1 --- records --- N Transaction,
--                          Transfer 0..1 --- generates --- N Transaction)
--    One row per posting shown in the customer's transaction history.
-- ---------------------------------------------------------------------
CREATE TABLE account_transaction (
    txn_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    account_no     CHAR(10)      NOT NULL,
    transfer_id    INT UNSIGNED  NULL,                 -- NULL for deposits, fees, interest
    txn_type       VARCHAR(6)    NOT NULL,
    amount         DECIMAL(12,2) NOT NULL,
    description    VARCHAR(100)  NOT NULL,
    balance_after  DECIMAL(12,2) NOT NULL,
    posted_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_account_transaction PRIMARY KEY (txn_id),
    CONSTRAINT fk_txn_account  FOREIGN KEY (account_no)
        REFERENCES account (account_no) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_txn_transfer FOREIGN KEY (transfer_id)
        REFERENCES transfer (transfer_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_txn_type   CHECK (txn_type IN ('DEBIT', 'CREDIT')),
    CONSTRAINT ck_txn_amount CHECK (amount > 0)
) ENGINE = InnoDB;

-- Supports "history for one account between two dates, newest first"
CREATE INDEX ix_txn_account_date ON account_transaction (account_no, posted_at);

-- ---------------------------------------------------------------------
-- 5. STAFF
-- ---------------------------------------------------------------------
CREATE TABLE staff (
    staff_id       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    first_name     VARCHAR(50)   NOT NULL,
    last_name      VARCHAR(50)   NOT NULL,
    email          VARCHAR(100)  NOT NULL,
    username       VARCHAR(30)   NOT NULL,
    password_hash  VARCHAR(255)  NOT NULL,
    staff_role     VARCHAR(20)   NOT NULL DEFAULT 'SUPPORT',
    CONSTRAINT pk_staff PRIMARY KEY (staff_id),
    CONSTRAINT uq_staff_username UNIQUE (username),
    CONSTRAINT uq_staff_email    UNIQUE (email),
    CONSTRAINT ck_staff_role CHECK (staff_role IN ('SUPPORT', 'SUPERVISOR', 'AUDITOR'))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 6. TRANSFER_REVIEW  (Staff M --- reviews --- N Transfer)
--    Relationship table; also the staff audit trail (N5).
-- ---------------------------------------------------------------------
CREATE TABLE transfer_review (
    staff_id     INT UNSIGNED  NOT NULL,
    transfer_id  INT UNSIGNED  NOT NULL,
    reviewed_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason       VARCHAR(200)  NULL,
    CONSTRAINT pk_transfer_review PRIMARY KEY (staff_id, transfer_id, reviewed_at),
    CONSTRAINT fk_review_staff    FOREIGN KEY (staff_id)
        REFERENCES staff (staff_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_review_transfer FOREIGN KEY (transfer_id)
        REFERENCES transfer (transfer_id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE = InnoDB;

CREATE INDEX ix_review_transfer ON transfer_review (transfer_id);

-- =====================================================================
-- Stored procedure: atomic, idempotent transfer between own accounts
-- (F4-F7, N3). Re-sending the same request_id returns the original row.
-- =====================================================================
DELIMITER //
CREATE PROCEDURE sp_transfer (
    IN p_customer_id INT UNSIGNED,
    IN p_request_id  CHAR(36),
    IN p_source      CHAR(10),
    IN p_dest        CHAR(10),
    IN p_amount      DECIMAL(12,2)
)
BEGIN
    DECLARE v_existing INT UNSIGNED DEFAULT NULL;
    DECLARE v_src_owner, v_dst_owner INT UNSIGNED DEFAULT NULL;
    DECLARE v_src_bal, v_dst_bal DECIMAL(12,2);
    DECLARE v_id INT UNSIGNED;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    -- Duplicate click / retry: return the original result, move nothing.
    SELECT transfer_id INTO v_existing
      FROM transfer WHERE request_id = p_request_id;
    IF v_existing IS NOT NULL THEN
        SELECT * FROM transfer WHERE transfer_id = v_existing;
    ELSE
        IF p_amount IS NULL OR p_amount <= 0 OR p_amount <> ROUND(p_amount, 2) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Enter an amount greater than $0.';
        END IF;
        IF p_source = p_dest THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose two different accounts.';
        END IF;

        START TRANSACTION;

        -- Lock both rows in a fixed order to avoid deadlocks and lost updates.
        SELECT customer_id, available_balance INTO v_src_owner, v_src_bal
          FROM account WHERE account_no = p_source AND status = 'ACTIVE' FOR UPDATE;
        SELECT customer_id, available_balance INTO v_dst_owner, v_dst_bal
          FROM account WHERE account_no = p_dest   AND status = 'ACTIVE' FOR UPDATE;

        IF v_src_owner IS NULL OR v_dst_owner IS NULL
           OR v_src_owner <> p_customer_id OR v_dst_owner <> p_customer_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Both accounts must be your own active accounts.';
        END IF;
        IF v_src_bal < p_amount THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Insufficient funds in the source account.';
        END IF;

        INSERT INTO transfer (reference_no, request_id, source_acct_no, dest_acct_no, amount, status)
        VALUES ('TRF000000', p_request_id, p_source, p_dest, p_amount, 'PENDING');
        SET v_id = LAST_INSERT_ID();
        UPDATE transfer
           SET reference_no = CONCAT('TRF', LPAD(v_id, 6, '0')),
               status = 'COMPLETED', completed_at = NOW()
         WHERE transfer_id = v_id;

        UPDATE account SET available_balance = available_balance - p_amount WHERE account_no = p_source;
        UPDATE account SET available_balance = available_balance + p_amount WHERE account_no = p_dest;

        INSERT INTO account_transaction (account_no, transfer_id, txn_type, amount, description, balance_after)
        VALUES (p_source, v_id, 'DEBIT',  p_amount, CONCAT('Transfer to ',   RIGHT(p_dest, 4)),   v_src_bal - p_amount),
               (p_dest,   v_id, 'CREDIT', p_amount, CONCAT('Transfer from ', RIGHT(p_source, 4)), v_dst_bal + p_amount);

        COMMIT;
        SELECT * FROM transfer WHERE transfer_id = v_id;
    END IF;
END //
DELIMITER ;

-- =====================================================================
-- Sample data (matches the Lab 3 GUI prototype)
-- Demo sign-ins for the web app (passwords are stored only as PBKDF2 hashes):
--   customers: mlopez / Maria2026!   jchen / James2026!
--   staff:     arivera / Staff2026!
-- =====================================================================
INSERT INTO customer (first_name, last_name, email, phone, username, password_hash) VALUES
 ('Maria', 'Lopez', 'maria.lopez@example.com', '555-0101', 'mlopez', 'pbkdf2:sha256:600000$HOAJWXU4LsEENrp5$872aa9211dc1874faad937df8294c1613ceb0e4dd79f698f0105e23367e418c1'),
 ('James', 'Chen',  'james.chen@example.com',  '555-0102', 'jchen',  'pbkdf2:sha256:600000$KCmLzKsWzQ4kAhvs$116b7700198c241989e69802f09014996b38c0bd1ae05d7a05c95fc3792b3fec');

INSERT INTO account (account_no, customer_id, account_type, available_balance, opened_date) VALUES
 ('4000001024', 1, 'CHECKING', 2500.00, '2024-03-01'),
 ('4000002048', 1, 'SAVINGS',  1200.00, '2024-03-01'),
 ('4000003072', 2, 'CHECKING',  800.00, '2025-01-15');

INSERT INTO account_transaction (account_no, txn_type, amount, description, balance_after, posted_at) VALUES
 ('4000001024', 'CREDIT', 2500.00, 'Opening deposit', 2500.00, '2026-10-01 09:00:00'),
 ('4000002048', 'CREDIT', 1200.00, 'Opening deposit', 1200.00, '2026-10-01 09:05:00'),
 ('4000003072', 'CREDIT',  800.00, 'Opening deposit',  800.00, '2026-10-02 10:00:00');

INSERT INTO staff (first_name, last_name, email, username, password_hash, staff_role) VALUES
 ('Alex', 'Rivera', 'alex.rivera@bank.example', 'arivera', 'pbkdf2:sha256:600000$2FPExxwFDrVsd4Rt$a433307b6675231ee5801cf86691ca2ad7d93f3f9f72d7d03a95225a307780cf', 'SUPPORT');

-- $200 from checking ....1024 to savings ....2048 (the GUI walkthrough)
CALL sp_transfer(1, '6f1c2a8e-0d3b-4c1e-9a77-2b5f1e0c9d01', '4000001024', '4000002048', 200.00);
-- Same request again (double click): returns TRF000001, balances unchanged
CALL sp_transfer(1, '6f1c2a8e-0d3b-4c1e-9a77-2b5f1e0c9d01', '4000001024', '4000002048', 200.00);

INSERT INTO transfer_review (staff_id, transfer_id, reason)
VALUES (1, 1, 'Customer called to confirm transfer status');

-- =====================================================================
-- Example queries
-- =====================================================================
-- F2: accounts for a signed-in customer, numbers masked
SELECT CONCAT('****', RIGHT(account_no, 4)) AS account, account_type, available_balance
  FROM account WHERE customer_id = 1;

-- F3: history for one account within a date range, newest first
SELECT posted_at, description, txn_type, amount, balance_after
  FROM account_transaction
 WHERE account_no = '4000001024'
   AND posted_at >= '2026-10-01' AND posted_at < DATE_ADD('2026-10-31', INTERVAL 1 DAY)
 ORDER BY posted_at DESC;

-- F10: staff search by reference number
SELECT t.reference_no, t.amount, t.status, t.created_at,
       CONCAT('****', RIGHT(t.source_acct_no, 4)) AS from_acct,
       CONCAT('****', RIGHT(t.dest_acct_no, 4))   AS to_acct
  FROM transfer t
 WHERE t.reference_no = 'TRF000001';

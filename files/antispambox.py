# Open a connection in IDLE mode and wait for notifications from the
# server.

from imapclient import IMAPClient
import subprocess
import json
import sys
import logging
import time
from logging.handlers import TimedRotatingFileHandler

# configure logging
logger = logging.getLogger("Antispambox")
logger.setLevel(logging.INFO)

# rotate the logfile every 24 hours
handler = TimedRotatingFileHandler('/var/log/antispambox.log',
                                   when="H",
                                   interval=24,
                                   backupCount=5)


# format the logfile (add timestamp etc)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
logger.addHandler(handler)

# log to stdout
logger.addHandler(logging.StreamHandler())

# read account information
try:

    with open("/root/accounts/imap_accounts.json", 'r') as f:
        datastore = json.load(f)

    HOST = datastore["antispambox"]["account"]["server"]
    USERNAME = datastore["antispambox"]["account"]["user"]
    PASSWORD = datastore["antispambox"]["account"]["password"]
    JUNK = datastore["antispambox"]["account"]["junk_folder"]
    INPUT = datastore["antispambox"]["account"]["inbox_folder"]
    HAMTRAIN = datastore["antispambox"]["account"]["ham_train_folder"]
    SPAMTRAIN = datastore["antispambox"]["account"]["spam_train_folder"]
    SPAMTRAIN2 = datastore["antispambox"]["account"]["spam_train_folder2"]
    CACHEPATH = "rspamd"
except IndexError:
    print("ERROR: was not able to read imap_accounts.json.")
    sys.exit(1)


def scan_spam():
    for engine, training in (('irsd', SPAMTRAIN2), ('isbg', SPAMTRAIN)):
        command = ['/usr/local/bin/' + engine]
        if engine == 'isbg':
            command.append('--spamc')
        command += ['--imaphost', HOST, '--imapuser', USERNAME,
                    '--imappasswd', PASSWORD, '--spaminbox', JUNK,
                    '--imapinbox', INPUT, '--learnhambox', HAMTRAIN,
                    '--learnspambox', training]
        if engine == 'irsd':
            command += ['--cachepath', CACHEPATH]
        command += ['--delete', '--expunge', '--partialrun', '500']
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.communicate()
        # Do not log command arguments or client output containing mailbox data.
        if process.returncode:
            logger.warning('%s scan failed (exit=%s)', engine, process.returncode)
        else:
            logger.info('%s scan completed', engine)


def login():
    # login to server
    while True:
        try:
            server = IMAPClient(HOST)
            server.login(USERNAME, PASSWORD)
            server.select_folder(INPUT)
            # Start IDLE mode
            server.idle()
            logger.info("Connection is now in IDLE mode")
        except Exception as e:
            logger.info("Failed to connect - try again")
            logger.warning("IMAP connection failed (%s); retrying", type(e).__name__)
            time.sleep(10)
            continue
        return server


def logoff(server):
    server.idle_done()
    logger.info("\nIDLE mode done")
    server.logout()


def pushing(server):
    """run IMAP idle until an exception (like no response) happens"""
    count = 0
    while True:
        try:
            # Wait for up to 30 seconds for an IDLE response
            responses = server.idle_check(timeout=29)

            if responses:
                logger.info(responses)
                
            else:
                logger.info("Response: nothing")
                count = count + 1
             
            if count > 5:
                logger.info("No responses from Server - Scan for Spam, then Restart")
                scan_spam()
                count = 0
                raise Exception("No response")

            for response in responses:
                count = 0
                if response[1].decode('UTF-8') == "RECENT" or response[1].decode('UTF-8') == "EXISTS":
                    scan_spam()

        except KeyboardInterrupt:
            break

        except Exception as e:
            logger.info("Push error")
            count = 0
            # logger.info(str(e.message))
            break


# run scan_spam once
scan_spam()


# run IMAP IDLE until CTRL-C is pressed.
while True:
    try:
        logger.info("Login to IMAP")
        server = login()
        logger.info("Start IAMP IDLE")
        pushing(server)
        logger.info("Logoff from IMAP")
        logoff(server)

    except KeyboardInterrupt:
        break
    except Exception as e:
        logger.info("Exception in Mainloop")
        # logger.info(str(e.message))

# logoff
logoff(server)
logger.info("Pushtest exited")

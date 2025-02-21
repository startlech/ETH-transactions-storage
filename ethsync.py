# Indexer for Ethereum to get transaction list by ETH address
# https://github.com/Adamant-im/ETH-transactions-storage
# 2021 ADAMANT Foundation (devs@adamant.im), Francesco Bonanno (mibofra@parrotsec.org),
# Guénolé de Cadoudal (guenoledc@yahoo.fr), Drew Wells (drew.wells00@gmail.com)
# 2020-2021 ADAMANT Foundation (devs@adamant.im): Aleksei Lebedev
# 2017-2020 ADAMANT TECH LABS LP (pr@adamant.im): Artem Brunov, Aleksei Lebedev
# v2.0

from os import environ
from web3 import Web3
from web3.middleware import geth_poa_middleware
import psycopg2
import time
import sys
import logging
from tqdm import tqdm
#from systemd.journal import JournalHandler

# Get env variables or set to default
dbname = environ.get("DB_NAME")
startBlock = environ.get("START_BLOCK") or "1"
confirmationBlocks = environ.get("CONFIRMATIONS_BLOCK") or "0"
nodeUrl = environ.get("ETH_URL")
pollingPeriod = environ.get("PERIOD") or "20"

if dbname == None:
    print('Add postgre database in env var DB_NAME')
    exit(2)

if nodeUrl == None:
    print('Add eth url in env var ETH_URL')
    exit(2)

# Connect to Ethereum node
if nodeUrl.startswith("http"):
    web3 = Web3(Web3.HTTPProvider(nodeUrl))
if nodeUrl.startswith("ws"):
    web3 = Web3(Web3.WebsocketProvider(nodeUrl)) # "ws://publicnode:8546"
if web3 == None:
    web3 = Web3(Web3.IPCProvider(nodeUrl)) # "/home/parity/.local/share/openethereum/jsonrpc.ipc"

web3.middleware_onion.inject(geth_poa_middleware, layer=0)

# Start logger
#logger = logging.getLogger("EthIndexerLog")
logger = logging.getLogger("eth-sync")
logger.setLevel(logging.INFO)

# File logger
#lfh = logging.FileHandler("/var/log/ethindexer.log")
lfh = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
lfh.setFormatter(formatter)
logger.addHandler(lfh)

# Systemd logger, if we want to user journalctl logs
# Install systemd-python and 
# decomment "#from systemd.journal import JournalHandler" up
#ljc = JournalHandler()
#formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
#ljc.setFormatter(formatter)
#logger.addHandler(ljc)

try:
    logger.info("Trying to connect to "+ dbname)
    conn = psycopg2.connect(dbname=dbname, user="rva", password="")
    conn.autocommit = True
    logger.info("Connected to the database")
except:
    logger.error("Unable to connect to database")
    exit(1)

# Delete last block as it may be not imparted in full
cur = conn.cursor()
cur.execute('DELETE FROM public.ethtxs WHERE block = (SELECT Max(block) from public.ethtxs)')
cur.close()
conn.close()

# Wait for the node to be in sync before indexing
logger.info("Waiting Ethereum node to be in sync...")

while web3.eth.syncing != False:
    # Change with the time, in second, do you want to wait
    # before cheking again, default is 5 minutes
    time.sleep(300)

logger.info("Ethereum node is synced!")

# Adds all transactions from Ethereum block
def insertion(block):
    time = block['timestamp']
    for trans in block['transactions']:       
        txhash = trans['hash'].hex()
        fr = trans['from']
        to = trans['to']
        cur.execute(
            'INSERT INTO public.ethtxs(time, txfrom, txto, block, txhash) VALUES (%s, %s, %s, %s, %s)',
            (time, fr, to, trans['blockNumber'], txhash))

# Fetch all of new (not in index) Ethereum blocks and add transactions to index
while True:
    try:
        conn = psycopg2.connect(dbname=dbname, user="rva", password="")
        conn.autocommit = True
    except:
        logger.error("Unable to connect to database")

    cur = conn.cursor()

    cur.execute('SELECT Max(block) from public.ethtxs')
    maxblockindb = cur.fetchone()[0]
    # On first start, we index transactions from a block number you indicate
    if maxblockindb is None:
        maxblockindb = int(startBlock)

    endblock = int(web3.eth.blockNumber) - int(confirmationBlocks)

    logger.info('Current best block in index: ' + str(maxblockindb) + '; in Ethereum chain: ' + str(endblock))

    for blockNo in tqdm(range(maxblockindb + 1, endblock)):
        block = web3.eth.get_block(blockNo, True)
        insertion(block)
    
    cur.close()
    conn.close()
    time.sleep(int(pollingPeriod))

#!/usr/bin/env python3
"""
Script để test DrowsinessDetection smart contract
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
INFURA_URL = os.environ.get('INFURA_URL')
CONTRACT_ADDRESS = os.environ.get('CONTRACT_ADDRESS')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY')

# Contract ABI
CONTRACT_ABI = [
    {
        "inputs": [],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "internalType": "string", "name": "userId", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "cameraId", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "imagePath", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "timestamp", "type": "string"},
            {"indexed": False, "internalType": "string", "name": "alertLevel", "type": "string"}
        ],
        "name": "DrowsinessDetected",
        "type": "event"
    },
    {
        "inputs": [
            {"internalType": "string", "name": "_userId", "type": "string"},
            {"internalType": "string", "name": "_cameraId", "type": "string"},
            {"internalType": "string", "name": "_imagePath", "type": "string"},
            {"internalType": "string", "name": "_timestamp", "type": "string"},
            {"internalType": "string", "name": "_alertLevel", "type": "string"}
        ],
        "name": "addDrowsinessEvent",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getTotalEvents",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "index", "type": "uint256"}],
        "name": "getEvent",
        "outputs": [
            {"internalType": "string", "name": "userId", "type": "string"},
            {"internalType": "string", "name": "cameraId", "type": "string"},
            {"internalType": "string", "name": "imagePath", "type": "string"},
            {"internalType": "string", "name": "timestamp", "type": "string"},
            {"internalType": "string", "name": "alertLevel", "type": "string"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

def test_contract():
    """Test smart contract functionality"""
    print("🧪 Testing DrowsinessDetection Contract")
    print("=" * 50)

    if not all([INFURA_URL, CONTRACT_ADDRESS, PRIVATE_KEY]):
        print("❌ Missing configuration. Check your .env file")
        return

    # Initialize Web3
    web3 = Web3(Web3.HTTPProvider(INFURA_URL))
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not web3.is_connected():
        print("❌ Cannot connect to Ethereum network")
        return

    print(f"✅ Connected to network (Chain ID: {web3.eth.chain_id})")

    # Initialize contract
    try:
        contract = web3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
        print(f"✅ Contract loaded at: {CONTRACT_ADDRESS}")
    except Exception as e:
        print(f"❌ Failed to load contract: {e}")
        return

    # Test reading functions
    try:
        total_events = contract.functions.getTotalEvents().call()
        print(f"📊 Total events stored: {total_events}")
    except Exception as e:
        print(f"❌ Failed to read total events: {e}")
        return

    # Test adding event
    account = web3.eth.account.from_key(PRIVATE_KEY)
    print(f"📧 Using account: {account.address}")

    # Check balance
    balance = web3.eth.get_balance(account.address)
    balance_eth = web3.from_wei(balance, 'ether')
    print(f"💰 Account balance: {balance_eth} ETH")

    if balance < web3.to_wei(0.001, 'ether'):
        print("❌ Insufficient funds for transaction")
        return

    # Add test event
    try:
        nonce = web3.eth.get_transaction_count(account.address)

        test_event = {
            "userId": "test_user",
            "cameraId": "TEST_CAM_001",
            "imagePath": "captured_images/test_alert.jpg",
            "timestamp": "2024-01-01_12:00:00",
            "alertLevel": "test"
        }

        txn = contract.functions.addDrowsinessEvent(
            test_event["userId"],
            test_event["cameraId"],
            test_event["imagePath"],
            test_event["timestamp"],
            test_event["alertLevel"]
        ).build_transaction({
            'chainId': 11155111,
            'gas': 200000,
            'gasPrice': web3.eth.gas_price,
            'nonce': nonce,
        })

        signed_txn = web3.eth.account.sign_transaction(txn, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)

        print(f"📤 Test transaction sent: {web3.to_hex(tx_hash)}")
        print("⏳ Waiting for confirmation...")

        tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"✅ Transaction confirmed in block: {tx_receipt.blockNumber}")

        # Verify event was added
        new_total = contract.functions.getTotalEvents().call()
        print(f"📊 New total events: {new_total}")

        if new_total > total_events:
            print("✅ Event successfully added to blockchain!")

            # Read the event back
            event_data = contract.functions.getEvent(total_events).call()
            print(f"📋 Retrieved event: {event_data}")

        else:
            print("⚠️ Event count didn't increase")

    except Exception as e:
        print(f"❌ Transaction failed: {e}")

if __name__ == "__main__":
    test_contract()
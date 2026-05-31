#!/usr/bin/env python3
"""
Demo script để test MetaMask integration
Chạy script này để test kết nối Ethereum mà không cần camera
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import os

# Cấu hình (thay bằng thông tin thật của bạn)
INFURA_URL = os.environ.get('INFURA_URL', 'https://sepolia.infura.io/v3/YOUR_PROJECT_ID')
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', '0xYourPrivateKey')

def test_web3_connection():
    """Test kết nối Web3"""
    print("🔗 Testing Web3 connection...")

    # Khởi tạo Web3
    web3 = Web3(Web3.HTTPProvider(INFURA_URL))
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if web3.is_connected():
        print("✅ Connected to Ethereum network")
        print(f"   Network ID: {web3.eth.chain_id}")
        print(f"   Latest block: {web3.eth.block_number}")

        # Test account
        if PRIVATE_KEY != '0xYourPrivateKey':
            account = web3.eth.account.from_key(PRIVATE_KEY)
            balance = web3.eth.get_balance(account.address)
            print(f"   Account: {account.address}")
            print(f"   Balance: {web3.from_wei(balance, 'ether')} ETH")
        else:
            print("   ⚠️  Set PRIVATE_KEY environment variable for account testing")

    else:
        print("❌ Failed to connect to Ethereum network")
        print("   Check your INFURA_URL")

    return web3.is_connected()

def simulate_drowsiness_event():
    """Mô phỏng gửi sự kiện buồn ngủ lên Ethereum"""
    print("\n🚨 Simulating drowsiness detection event...")

    web3 = Web3(Web3.HTTPProvider(INFURA_URL))
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not web3.is_connected():
        print("❌ Cannot simulate - not connected to Ethereum")
        return

    if PRIVATE_KEY == '0xYourPrivateKey':
        print("❌ Set PRIVATE_KEY environment variable to simulate transactions")
        return

    # Giả lập dữ liệu sự kiện
    user_id = "driver1"
    camera_id = "CAMERA_001"
    image_path = "captured_images/alert_20260513_100000.jpg"
    timestamp = "2026-05-13 10:00:00"
    alert_level = "high"

    print(f"   User: {user_id}")
    print(f"   Camera: {camera_id}")
    print(f"   Alert Level: {alert_level}")
    print(f"   Timestamp: {timestamp}")

    # Trong thực tế, đây sẽ là contract call
    # contract.functions.addDrowsinessEvent(user_id, camera_id, image_path, timestamp, alert_level)

    print("✅ Event would be sent to smart contract")
    print("   (Deploy contract first to enable real transactions)")

if __name__ == "__main__":
    print("🦊 MetaMask Integration Demo")
    print("=" * 40)

    connected = test_web3_connection()
    if connected:
        simulate_drowsiness_event()

    print("\n📋 Next steps:")
    print("1. Get Infura project ID: https://infura.io")
    print("2. Create MetaMask wallet: https://metamask.io")
    print("3. Get Sepolia test ETH: https://sepoliafaucet.com")
    print("4. Deploy DrowsinessDetection.sol on Remix")
    print("5. Update CONTRACT_ADDRESS in testAmThanh.py")
    print("6. Set environment variables: INFURA_URL, PRIVATE_KEY")
    print("7. Run: python testAmThanh.py")
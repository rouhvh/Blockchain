# Hệ thống phát hiện buồn ngủ với MetaMask Integration

## Tổng quan
Dự án này tích hợp camera AI phát hiện buồn ngủ với blockchain Ethereum thông qua MetaMask. Khi phát hiện buồn ngủ, hệ thống sẽ:
- Lưu ảnh cảnh báo vào thư mục `captured_images/`
- Gửi sự kiện lên local blockchain (blockchain.py)
- Gửi transaction lên Ethereum smart contract để lưu trữ immutable

## Cài đặt

### 1. Cài đặt dependencies
```bash
pip install -r requirements.txt
pip install web3
```

### 2. Setup MetaMask
1. **Cài đặt MetaMask**: https://metamask.io/download/
2. **Tạo ví mới** hoặc import ví hiện có
3. **Thêm Sepolia testnet**:
   - Network Name: Sepolia
   - RPC URL: https://rpc.sepolia.org
   - Chain ID: 11155111
   - Currency Symbol: SepoliaETH
4. **Lấy test ETH**: https://sepoliafaucet.com/
5. **Lấy private key**: Settings > Security & Privacy > Reveal Private Key

### 3. Setup Infura
1. **Tạo tài khoản**: https://infura.io/
2. **Tạo project mới** cho Sepolia testnet
3. **Copy Project ID** để dùng trong INFURA_URL

### 4. Deploy Smart Contract
**Tùy chọn A: Sử dụng script tự động**
```bash
pip install python-dotenv
python deploy_contract.py
```

**Tùy chọn B: Manual deploy với Remix**
1. **Mở Remix IDE**: https://remix.ethereum.org/
2. **Upload file** `DrowsinessDetection.sol`
3. **Compile** với Solidity version ^0.8.0
4. **Deploy** trên Sepolia network (kết nối MetaMask)
5. **Copy contract address** sau khi deploy thành công

### 5. Cấu hình
Trong `testAmThanh.py`, cập nhật các biến sau:
```python
INFURA_URL = "https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"
CONTRACT_ADDRESS = "0xYourDeployedContractAddress"
PRIVATE_KEY = "0xYourMetaMaskPrivateKey"
```

Hoặc sử dụng environment variables:
```bash
export INFURA_URL="https://sepolia.infura.io/v3/YOUR_PROJECT_ID"
export PRIVATE_KEY="0xYourPrivateKey"
```

## MetaMask và Remix IDE

MetaMask là ví trình duyệt cho phép người dùng quản lý tài khoản Ethereum và ký giao dịch.  Trong dự án này, MetaMask được dùng để kết nối ví người dùng với giao diện web, xác thực và ký các giao dịch gửi tới smart contract (ví dụ: `DrowsinessDetection.sol`) khi hệ thống phát hiện sự kiện buồn ngủ. Khi cần gửi transaction lên Ethereum testnet, ứng dụng sẽ tạo transaction và yêu cầu người dùng xác nhận trong MetaMask.

Remix IDE là môi trường phát triển Solidity trực tuyến để viết, biên dịch và triển khai smart contract. Trong dự án, Remix hữu ích để thử nghiệm và triển khai thủ công file `DrowsinessDetection.sol` lên Sepolia; tuy nhiên dự án cũng cung cấp các script tự động như `deploy_contract.py` và `deploy_manual.py` để deploy thông qua Infura/Web3 khi cần tự động hóa.

## Test kết nối
Chạy script test để kiểm tra:
```bash
python test_metamask.py
```

## Test deployment
Sau khi deploy contract, test với script:
```bash
python test_contract.py
```

## Chạy hệ thống
```bash
python testAmThanh.py
```

Truy cập: http://localhost:5000

## API Endpoints
- `GET /api/ethereum/status` - Kiểm tra kết nối Ethereum
- `GET /api/events/drowsiness` - Lấy danh sách sự kiện buồn ngủ
- `GET /api/blockchain/status` - Trạng thái local blockchain

## Cách hoạt động
1. **Camera monitoring**: OpenCV phát hiện khuôn mặt và mắt
2. **Drowsiness detection**: AI model phân tích trạng thái mắt
3. **Alert trigger**: Khi mắt nhắm > 2 giây, trigger cảnh báo
4. **Image capture**: Lưu ảnh cảnh báo vào `captured_images/`
5. **Local blockchain**: Gửi sự kiện lên blockchain local
6. **Ethereum transaction**: Gửi transaction lên smart contract
7. **MetaMask prompt**: User xác nhận transaction trong MetaMask

## Smart Contract Functions
```solidity
// Thêm sự kiện buồn ngủ
function addDrowsinessEvent(
    string memory userId,
    string memory cameraId,
    string memory imagePath,
    string memory timestamp,
    string memory alertLevel
) public

// Lấy tổng số sự kiện
function getTotalEvents() public view returns (uint256)

// Lấy sự kiện theo index
function getEvent(uint256 index) public view returns (DrowsinessEvent memory)
```

## Lưu ý bảo mật
- ⚠️ **Không dùng private key thật** trong production code
- Sử dụng **environment variables** cho sensitive data
- Implement **proper authentication** cho API calls
- **Encrypt private keys** khi lưu trữ
- Sử dụng **hardware wallets** cho production

## Troubleshooting
- **Connection failed**: Kiểm tra INFURA_URL và network connectivity
- **Transaction failed**: Đảm bảo đủ ETH trong ví và gas price hợp lý
- **MetaMask not prompting**: Kiểm tra network configuration trong MetaMask
- **Contract not found**: Verify CONTRACT_ADDRESS đúng và contract đã deploy

## Development
- Local blockchain: `blockchain.py`
- User management: `user_identity.py`
- Camera processing: OpenCV + TensorFlow models
- Web interface: Flask templates
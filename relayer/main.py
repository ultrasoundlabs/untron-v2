import asyncio
from hashlib import sha256
import os
import json
from datetime import datetime
from web3 import Web3
from dotenv import load_dotenv
from aiohttp import ClientSession
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Load environment variables
load_dotenv()

# Configuration
ETH_NODE = os.getenv("RPC_URL")
CONTRACT_ADDRESS = os.getenv("UNTRON_CONTRACT_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
BACKUP_FILE = "relayer/backup.txt"  # Only for Ethereum blocks
# Flag to enable mock transfers
MOCK_TRANSFERS = os.getenv("MOCK_TRANSFERS", "false").lower() == "true"
# Number of mock transfers to simulate
MOCK_TRANSFER_COUNT = int(os.getenv("MOCK_TRANSFER_COUNT", "5"))
# Delay between mock transfers in seconds
MOCK_TRANSFER_DELAY = int(os.getenv("MOCK_TRANSFER_DELAY", "10"))
# Receiver addresses from .env
RECEIVER_ADDRESSES = os.getenv("RECEIVER_ADDRESSES", "").split(",")

# USDT TRC20 token contract address on Tron
TRON_USDT_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Load contract ABI from a file or define it inline
CONTRACT_ABI = json.load(open("out/UntronV2.json"))["abi"]

# Setup clients
w3 = Web3(Web3.HTTPProvider(ETH_NODE))
contract = w3.eth.contract(
    address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=CONTRACT_ABI
)

# Initialize Ethereum account
account = w3.eth.account.from_key(PRIVATE_KEY)

# Create locks for thread safety
active_receivers_lock = asyncio.Lock()
seen_txs_lock = asyncio.Lock()

# Dictionary to track active receivers and their order details
active_receivers = {}
seen_txs = {}

# Initialize FastAPI app
app = FastAPI(title="Untron Relayer API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helper functions
def log_message(message):
    """Helper function to log messages with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    open("relayer/log.txt", "a").write(f"[{timestamp}] {message}\n")


async def listen_for_open_orders():
    """Listen for open orders and process them"""
    log_message("Starting open orders listener...")

    # start from current block
    last_block = w3.eth.block_number

    try:
        while True:
            # Get the current block number
            current_block = w3.eth.block_number

            # Only process if we have new blocks
            if current_block > last_block:
                log_message(
                    f"Processing blocks from {last_block + 1} to {current_block}"
                )

                # Get OrderCreated events
                created_events = contract.events.OrderCreated.get_logs(
                    from_block=last_block + 1, to_block=current_block
                )

                # Get OrderClosed events
                closed_events = contract.events.OrderClosed.get_logs(
                    from_block=last_block + 1, to_block=current_block
                )

                # Process OrderCreated events
                for event in created_events:
                    args = event["args"]
                    receiver = args["receiver"]

                    async with active_receivers_lock:
                        active_receivers[receiver] = 0
                    log_message(f"New order created for receiver: {receiver.hex()}")

                # Process OrderClosed events
                for event in closed_events:
                    args = event["args"]
                    receiver = args["receiver"]

                    async with active_receivers_lock:
                        if receiver in active_receivers:
                            del active_receivers[receiver]
                            log_message(f"Order closed for receiver: {receiver.hex()}")

                # Update the last processed block and backup
                last_block = current_block

            # Wait before checking for new events
            await asyncio.sleep(2)

    except Exception as e:
        log_message(f"Error in open orders listener: {e}")
        # Restart the listener after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(listen_for_open_orders())


async def listen_for_usdt_transfers():
    """Listen for USDT transfers and process them"""
    async with ClientSession() as session:
        # Get initial block number from getnowblock
        try:
            response = await session.get(
                "https://api.trongrid.io/wallet/getnowblock",
                headers={"TRON-PRO-API-KEY": os.getenv("TRONGRID_API_KEY")},
            )
            data = await response.json()
            last_processed_block = data["block_header"]["raw_data"]["number"]
            log_message(f"Starting from block: {last_processed_block}")
        except Exception as e:
            log_message(f"Error getting initial block: {str(e)}")
            raise

        while True:
            try:
                # Always check current block before processing to ensure we don't go beyond the blockchain's latest block
                response = await session.get(
                    "https://api.trongrid.io/wallet/getnowblock",
                    headers={"TRON-PRO-API-KEY": os.getenv("TRONGRID_API_KEY")},
                )
                data = await response.json()
                current_block = data["block_header"]["raw_data"]["number"]

                # Ensure we're not beyond the blockchain's latest block
                if last_processed_block > current_block:
                    await asyncio.sleep(1)
                    continue

                # Process all pages of events for the current block
                next_url = f"https://api.trongrid.io/v1/blocks/{last_processed_block}/events"
                while next_url:
                    response = await session.get(
                        next_url,
                        params={"limit": "200"},
                        headers={"TRON-PRO-API-KEY": os.getenv("TRONGRID_API_KEY")},
                    )
                    data = await response.json()

                    if not data.get("data"):
                        log_message(data)
                        break

                    log_message(
                        f"Processing {len(data['data'])} events of block {last_processed_block}"
                    )

                    for event in data["data"]:
                        if (
                            event["contract_address"] != TRON_USDT_ADDRESS
                            or event["event_name"] != "Transfer"
                        ):
                            continue

                        event_hash = sha256(json.dumps(event).encode()).hexdigest()

                        # Check if we've seen this transaction
                        async with seen_txs_lock:
                            if event_hash in seen_txs:
                                continue
                            seen_txs[event_hash] = True

                        # Check if receiver is active
                        async with active_receivers_lock:
                            if bytes.fromhex(event["result"]["to"][2:]) in active_receivers:
                                log_message(
                                    f"USDT transfer received for receiver: {event['result']['to']}"
                                )
                                # Create task without waiting for completion
                                asyncio.create_task(process_usdt_transfer(event))

                    # Check if there are more pages to process
                    next_url = data.get("meta", {}).get("links", {}).get("next")
                    if next_url:
                        log_message(f"Fetching next page of events from: {next_url}")

                # Update last processed block
                last_processed_block += 1

            except Exception as e:
                log_message(f"Error in USDT transfer listener: {str(e)}")

            await asyncio.sleep(1)


async def process_usdt_transfer(event):
    """Process USDT transfer event"""
    receiver = bytes.fromhex(event["result"]["to"][2:])
    amount = int(event["result"]["value"])
    log_message(
        f"Processing USDT transfer for receiver: {receiver.hex()}, amount: {amount}"
    )

    async with active_receivers_lock:
        if receiver not in active_receivers:
            return  # Receiver no longer active
        active_receivers[receiver] += amount
        current_amount = active_receivers[receiver]

    tx = contract.functions.setClaim(receiver, current_amount).build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 1000000,
        }
    )
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    log_message(f"Set claim transaction sent: {tx_hash.hex()}")


async def mock_usdt_transfers():
    """Simulate USDT transfers for testing purposes"""
    while True:
        async with active_receivers_lock:
            if not active_receivers:
                await asyncio.sleep(MOCK_TRANSFER_DELAY)
                continue

            # Get a random active receiver
            receiver = next(iter(active_receivers))
            amount = 10000000  # 10 USDT (6 decimals)

            # Create mock event data
            mock_event = {"result": {"to": receiver, "value": str(amount)}}

            log_message(
                f"Mock USDT transfer for receiver: {receiver}, amount: {amount}"
            )
            await process_usdt_transfer(mock_event)

        await asyncio.sleep(MOCK_TRANSFER_DELAY)


@app.get("/status")
async def get_status():
    """API endpoint to show receiver addresses not currently active and contract status"""
    available_receivers = []

    async with active_receivers_lock:
        for addr in RECEIVER_ADDRESSES:
            if not addr:  # Skip empty addresses
                continue

            # Convert hex string to bytes for comparison with active_receivers keys
            addr_bytes = bytes.fromhex(addr)

            log_message(f"Active receivers: {active_receivers}")
            log_message(f"addr_bytes: {addr_bytes}")

            if addr_bytes not in active_receivers:
                available_receivers.append(addr)

    # Get liquidity information
    liquidity_info = {"status": "error", "availableLiquidity": 0, "rate": 0}
    try:
        lp_info = contract.functions.liquidityProviders(account.address).call()
        liquidity_info = {
            "status": "healthy",
            "availableReceivers": available_receivers,
            "availableLiquidity": lp_info[0],
            "rate": lp_info[1],
            "currentBlock": w3.eth.block_number,
            "contractAddress": CONTRACT_ADDRESS,
            "relayerAddress": account.address,
        }
    except Exception as e:
        log_message(f"Error fetching liquidity data: {str(e)}")
        liquidity_info["error"] = str(e)

    return liquidity_info


async def start_api():
    """Start the FastAPI server"""
    config = uvicorn.Config(app, host="0.0.0.0", port=8455, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Main function to run all tasks"""
    tasks = [listen_for_open_orders(), listen_for_usdt_transfers(), start_api()]

    if MOCK_TRANSFERS:
        log_message("Mock transfers enabled - starting mock transfer simulation")
        tasks.append(mock_usdt_transfers())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

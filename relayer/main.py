import asyncio
import os
import json
from datetime import datetime
from web3 import Web3
from tronpy import AsyncTron
from tronpy.providers import AsyncHTTPProvider
from dotenv import load_dotenv

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
# Delay between TronGrid API requests to avoid rate limiting
TRONGRID_REQUEST_DELAY = int(os.getenv("TRONGRID_REQUEST_DELAY", "1"))

# USDT TRC20 token contract address on Tron
TRON_USDT_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Load contract ABI from a file or define it inline
CONTRACT_ABI = json.load(open("out/UntronV2.json"))["abi"]

# Setup clients
w3 = Web3(Web3.HTTPProvider(ETH_NODE))
tron_client = AsyncTron(
    AsyncHTTPProvider(
        api_key=os.getenv("TRONGRID_API_KEY")
    )
)
contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=CONTRACT_ABI)

# Initialize Ethereum account
account = w3.eth.account.from_key(PRIVATE_KEY)

# Create aiohttp session
http_client = None

# Order Manager data structure
active_orders = {}  # { receiver_address: { 'order': order_details, 'claim': current_claim } }

# Helper functions
def log_message(message):
    """Helper function to log messages with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def eth_address_to_tron(eth_address):
    """Convert Ethereum address format to Tron address format"""
    # Ensure the address has the '0x' prefix
    if not eth_address.startswith('0x'):
        eth_address = '0x' + eth_address
    return tron_client.to_base58check_address(eth_address)

def tron_to_eth_address(tron_address):
    """Convert Tron address to Ethereum address format"""
    addr_hex = tron_client.to_hex(tron_address)
    return addr_hex[2:]  # Remove '0x'

def read_backup_block(backup_file):
    """Read the last processed block number from the backup file"""
    try:
        if os.path.exists(backup_file):
            with open(backup_file, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
    except Exception as e:
        log_message(f"Error reading backup file: {e}")
    return None

def write_backup_block(block_number, backup_file):
    """Write the last processed block number to the backup file"""
    try:
        with open(backup_file, 'w') as f:
            f.write(str(block_number))
        log_message(f"Backup updated: Block {block_number}")
    except Exception as e:
        log_message(f"Error writing to backup file: {e}")

async def get_tron_block_by_timestamp(timestamp):
    """Get the approximate Tron block number for a given timestamp using binary search"""
    try:
        # Get current block
        current_block = await tron_client.get_latest_block_number()
        current_block_info = await tron_client.get_block(current_block)
        current_timestamp = current_block_info['block_header']['raw_data']['timestamp'] // 1000  # Convert from microseconds to seconds
        
        # If timestamp is in the future, return current block
        if timestamp > current_timestamp:
            return current_block
            
        # Binary search to find the block
        left = 0
        right = current_block
        
        while left <= right:
            mid = (left + right) // 2
            block_info = await tron_client.get_block(mid)
            block_timestamp = block_info['block_header']['raw_data']['timestamp'] // 1000  # Convert from microseconds to seconds
            
            if block_timestamp == timestamp:
                return mid
            elif block_timestamp < timestamp:
                left = mid + 1
            else:
                right = mid - 1
                
        # Return the closest block
        return left
    except Exception as e:
        log_message(f"Error finding Tron block for timestamp {timestamp}: {e}")
        return None

# Ethereum Event Listeners
async def listen_for_order_created():
    """Listen for OrderCreated events on the Ethereum contract"""
    log_message("Starting OrderCreated event listener...")
    
    # Get the last block from backup or start from current block
    last_block = read_backup_block(BACKUP_FILE)
    if last_block is None:
        last_block = w3.eth.block_number
        log_message(f"No backup found, starting from current block: {last_block}")
    else:
        log_message(f"Resuming from backup block: {last_block}")
    
    try:
        while True:
            # Get the current block number
            current_block = w3.eth.block_number
            
            # Only process if we have new blocks
            if current_block > last_block:
                # Get events from the last processed block to the current block
                events = contract.events.OrderCreated.get_logs(
                    fromBlock=last_block + 1,
                    toBlock=current_block
                )
                
                for event in events:
                    args = event['args']
                    
                    # Check if the LP is our account
                    if args['lp'] == account.address:
                        receiver = args['receiver'].hex()  # Convert bytes20 to hex string
                        tron_receiver = eth_address_to_tron(receiver)
                        
                        log_message(f"New order detected for receiver: {tron_receiver}")
                        log_message(f"Order details: Amount={args['amount']}, Rate={args['rate']}")
                        
                        # Initialize active order
                        active_orders[receiver] = {
                            'order': {
                                'creator': args['creator'],
                                'amount': args['amount'],
                                'rate': args['rate'],
                                'timestamp': args['timestamp'],
                                'beneficiary': args['beneficiary']
                            },
                            'claim': 0,
                            'tron_address': tron_receiver
                        }
                
                # Update the last processed block and backup
                last_block = current_block
                write_backup_block(last_block, BACKUP_FILE)
            
            # Wait before checking for new events
            await asyncio.sleep(2)
    except Exception as e:
        log_message(f"Error in OrderCreated listener: {e}")
        # Restart the listener after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(listen_for_order_created())

async def listen_for_order_closed():
    """Listen for OrderClosed events on the Ethereum contract"""
    log_message("Starting OrderClosed event listener...")
    
    # Get the last block from backup or start from current block
    last_block = read_backup_block(BACKUP_FILE)
    if last_block is None:
        last_block = w3.eth.block_number
        log_message(f"No backup found, starting from current block: {last_block}")
    else:
        log_message(f"Resuming from backup block: {last_block}")
    
    try:
        while True:
            # Get the current block number
            current_block = w3.eth.block_number
            
            # Only process if we have new blocks
            if current_block > last_block:
                # Get events from the last processed block to the current block
                events = contract.events.OrderClosed.get_logs(
                    fromBlock=last_block + 1,
                    toBlock=current_block
                )
                
                for event in events:
                    args = event['args']
                    receiver = args['receiver'].hex()  # Convert bytes20 to hex string
                    
                    if receiver in active_orders:
                        log_message(f"Order closed for receiver: {eth_address_to_tron(receiver)}")
                        log_message(f"Final amount: {args['atAmount']}")
                        
                        # Remove the order from active orders
                        del active_orders[receiver]
                
                # Update the last processed block and backup
                last_block = current_block
                write_backup_block(last_block, BACKUP_FILE)
            
            # Wait before checking for new events
            await asyncio.sleep(2)
    except Exception as e:
        log_message(f"Error in OrderClosed listener: {e}")
        # Restart the listener after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(listen_for_order_closed())

# Mock Tron Transfers
async def mock_tron_transfers():
    """Simulate Tron USDT transfers without actually sending transactions on the Tron chain"""
    if not MOCK_TRANSFERS:
        return
        
    log_message("Starting mock Tron USDT transfers")
    
    try:
        while True:
            # Exit if there are no active orders
            if not active_orders:
                await asyncio.sleep(10)
                continue
                
            for receiver_hex, order_data in list(active_orders.items()):
                tron_receiver = order_data['tron_address']
                order = order_data['order']
                current_claim = order_data['claim']
                
                # Calculate total amount and remaining amount
                total_amount = order['amount']
                remaining = total_amount - current_claim
                
                if remaining <= 0:
                    continue
                    
                # Calculate mock transfer amount (1/5 of remaining or everything if small amount)
                transfer_amount = min(remaining, remaining // 5 or remaining)
                if transfer_amount == 0:
                    continue
                
                # Update the cumulative claim
                new_claim = current_claim + transfer_amount
                
                # Log the mock transfer
                log_message(f"Mock USDT Transfer to {tron_receiver}")
                log_message(f"Amount: {transfer_amount/1_000_000} USDT")
                log_message(f"New claim: {new_claim/1_000_000} USDT")
                
                # Update the claim on Ethereum
                await update_claim_on_eth(receiver_hex, new_claim)
                
                # Update our local tracking
                active_orders[receiver_hex]['claim'] = new_claim
            
            # Wait before the next mock transfer cycle
            await asyncio.sleep(MOCK_TRANSFER_DELAY)
    except Exception as e:
        log_message(f"Error in mock Tron transfers: {e}")
        # Restart the mock transfers after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(mock_tron_transfers())

# Claim Updater
async def update_claim_on_eth(receiver_hex, claim_amount):
    """Update the claim amount on the Ethereum contract"""
    log_message(f"Updating claim for receiver {receiver_hex}: {claim_amount}")
    
    try:
        # Convert hex string back to bytes
        receiver_bytes = bytes.fromhex(receiver_hex)
        
        # Build the transaction
        tx = contract.functions.setClaim(receiver_bytes, claim_amount).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 500000,  # Set appropriate gas limit
            # Add gas price or max fee per gas if needed
        })
        
        # Sign the transaction
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        
        # Send the transaction
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        log_message(f"Claim update transaction sent: {tx_hash.hex()}")
        
        # Wait for transaction to be mined
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            log_message(f"Claim update successful: {claim_amount}")
        else:
            log_message(f"Claim update failed: {receipt}")
    except Exception as e:
        log_message(f"Error updating claim: {e}")

async def scan_tron_usdt_transfers():
    """Continuously scan for USDT transfers on Tron and match them with active orders"""
    log_message("Starting Tron USDT transfer scanner...")
    
    # Find the earliest order timestamp among active orders
    earliest_timestamp = None
    for order_data in active_orders.values():
        order_timestamp = order_data['order']['timestamp']
        if earliest_timestamp is None or order_timestamp < earliest_timestamp:
            earliest_timestamp = order_timestamp
    
    if earliest_timestamp is None:
        # If no active orders, start from current block
        last_block = await tron_client.get_latest_block_number()
        log_message(f"No active orders, starting from current block: {last_block}")
    else:
        # Convert timestamp to Tron block number
        last_block = await get_tron_block_by_timestamp(earliest_timestamp)
        if last_block is None:
            last_block = await tron_client.get_latest_block_number()
            log_message(f"Could not find block for timestamp {earliest_timestamp}, starting from current block: {last_block}")
        else:
            log_message(f"Starting from block {last_block} (timestamp: {earliest_timestamp})")
    
    try:
        while True:
            # Get the current block number
            current_block = await tron_client.get_latest_block_number()
            
            # Only process if we have new blocks
            if current_block > last_block:
                # Get events from the last processed block to the current block
                for block_num in range(last_block + 1, current_block + 1):
                    try:
                        # Get all transactions in the block
                        block = await tron_client.get_block(block_num)
                        log_message(f"Processing Tron block {block_num}")
                        
                        for tx in block['transactions']:
                            # Check if transaction was successful
                            if not tx.get('ret', [{}])[0].get('contractRet', '') == 'SUCCESS':
                                continue
                                
                            # Check if it's a USDT transfer
                            if tx['raw_data']['contract'][0]['type'] == 'TriggerSmartContract':
                                contract_address = tx['raw_data']['contract'][0]['parameter']['value']['contract_address']
                                
                                if contract_address == TRON_USDT_ADDRESS:
                                    # Decode the transfer data
                                    data = tx['raw_data']['contract'][0]['parameter']['value']['data']
                                    if data.startswith('a9059cbb'):  # Transfer function signature
                                        # Extract recipient and amount
                                        recipient = '41' + data[32:72]  # Add Tron prefix
                                        amount = int(data[72:], 16)
                                        
                                        # Convert recipient to base58 format
                                        tron_recipient = tron_client.to_base58check_address(recipient)
                                        
                                        # Check if this recipient has an active order
                                        for receiver_hex, order_data in list(active_orders.items()):
                                            if order_data['tron_address'] == tron_recipient:
                                                current_claim = order_data['claim']
                                                new_claim = current_claim + amount
                                                
                                                # Update the claim on Ethereum
                                                await update_claim_on_eth(receiver_hex, new_claim)
                                                
                                                # Update our local tracking
                                                active_orders[receiver_hex]['claim'] = new_claim
                                                
                                                log_message(f"USDT Transfer detected for {tron_recipient}")
                                                log_message(f"Amount: {amount/1_000_000} USDT")
                                                log_message(f"New claim: {new_claim/1_000_000} USDT")
                                                
                                                break
                    
                    except Exception as e:
                        log_message(f"Error processing block {block_num}: {e}")
                        continue
                
                # Update the last processed block
                last_block = current_block
            
            # Wait before checking for new blocks
            await asyncio.sleep(TRONGRID_REQUEST_DELAY)
            
    except Exception as e:
        log_message(f"Error in Tron USDT transfer scanner: {e}")
        # Restart the scanner after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(scan_tron_usdt_transfers())

# Main function
async def main():
    """Main entry point for the relayer"""
    log_message("Starting UntronV2 Relayer...")
    log_message(f"Ethereum Node: {ETH_NODE}")
    log_message(f"Contract Address: {CONTRACT_ADDRESS}")
    log_message(f"LP Address: {account.address}")
    
    try:
        # Create tasks for all services
        order_created_task = asyncio.create_task(listen_for_order_created())
        order_closed_task = asyncio.create_task(listen_for_order_closed())
        
        if MOCK_TRANSFERS:
            tron_task = asyncio.create_task(mock_tron_transfers())
        else:
            tron_task = asyncio.create_task(scan_tron_usdt_transfers())
        
        # Wait for all tasks
        await asyncio.gather(
            order_created_task,
            order_closed_task,
            tron_task
        )
    except KeyboardInterrupt:
        log_message("Relayer stopped by user")
    except Exception as e:
        log_message(f"Fatal error: {e}")
    finally:
        # Ensure http_client is closed when the program exits
        global http_client
        if http_client:
            await http_client.close()
            http_client = None

if __name__ == '__main__':
    asyncio.run(main())
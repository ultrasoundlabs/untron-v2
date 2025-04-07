import asyncio
import os
import json
from datetime import datetime
from web3 import Web3
from tronpy import AsyncTron
from tronpy.providers import AsyncHTTPProvider
from dotenv import load_dotenv
import aiohttp

# Load environment variables
load_dotenv()

# Configuration
ETH_NODE = os.getenv("RPC_URL")
CONTRACT_ADDRESS = os.getenv("UNTRON_CONTRACT_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
BACKUP_FILE = "relayer/backup.txt"
# Flag to enable mock transfers
MOCK_TRANSFERS = os.getenv("MOCK_TRANSFERS", "false").lower() == "true"
# Number of mock transfers to simulate
MOCK_TRANSFER_COUNT = int(os.getenv("MOCK_TRANSFER_COUNT", "5"))
# Delay between mock transfers in seconds
MOCK_TRANSFER_DELAY = int(os.getenv("MOCK_TRANSFER_DELAY", "10"))

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
active_orders = {}  # { receiver_address: { 'order': order_details, 'claim': current_claim, 'tron_listener': task } }

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

def read_backup_block():
    """Read the last processed block number from the backup file"""
    try:
        if os.path.exists(BACKUP_FILE):
            with open(BACKUP_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
    except Exception as e:
        log_message(f"Error reading backup file: {e}")
    return None

def write_backup_block(block_number):
    """Write the last processed block number to the backup file"""
    try:
        with open(BACKUP_FILE, 'w') as f:
            f.write(str(block_number))
        log_message(f"Backup updated: Block {block_number}")
    except Exception as e:
        log_message(f"Error writing to backup file: {e}")

# Ethereum Event Listeners
async def listen_for_order_created():
    """Listen for OrderCreated events on the Ethereum contract"""
    log_message("Starting OrderCreated event listener...")
    
    # Get the last block from backup or start from current block
    last_block = read_backup_block()
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
                            'tron_listener': asyncio.create_task(listen_tron_transfers(receiver, tron_receiver))
                        }
                
                # Update the last processed block and backup
                last_block = current_block
                write_backup_block(last_block)
            
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
    last_block = read_backup_block()
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
                        
                        # Cancel the Tron listener task
                        active_orders[receiver]['tron_listener'].cancel()
                        
                        # Remove the order from active orders
                        del active_orders[receiver]
                
                # Update the last processed block and backup
                last_block = current_block
                write_backup_block(last_block)
            
            # Wait before checking for new events
            await asyncio.sleep(2)
    except Exception as e:
        log_message(f"Error in OrderClosed listener: {e}")
        # Restart the listener after a short delay
        await asyncio.sleep(5)
        asyncio.create_task(listen_for_order_closed())

# Tron USDT Listener
async def listen_tron_transfers(receiver_hex, tron_receiver):
    """Listen for USDT transfers on Tron network for a specific receiver address"""
    log_message(f"Starting Tron USDT listener for: {tron_receiver}")
    
    # If mock transfers are enabled, use the mock function instead
    if MOCK_TRANSFERS:
        log_message(f"Mock transfers enabled. Will simulate {MOCK_TRANSFER_COUNT} transfers.")
        return await mock_tron_transfers(receiver_hex, tron_receiver)
    
    # Keep track of the last timestamp we processed
    last_timestamp = 0  # Start from 0 or a recent timestamp
    current_claim = 0
    
    # Create aiohttp session for this listener
    global http_client
    if http_client is None:
        http_client = aiohttp.ClientSession()
    
    try:
        # Prepare address filters in hex (0x format without '41' prefix)
        target_hex = tron_client.to_hex_address(tron_receiver)  # e.g. "41...1234"
        target_filter = "0x" + target_hex[2:].lower()  # e.g. "0x...1234"
        contract_hex = tron_client.to_hex_address(TRON_USDT_ADDRESS)  # "41..." format for URL
        
        while True:
            try:
                # Query TronGrid for new Transfer events since last_timestamp
                params = {
                    "only_confirmed": "false",
                    "event_name": "Transfer",
                    "min_timestamp": str(last_timestamp),
                    "order_by": "block_timestamp,asc",
                    "limit": "200",
                    "filters": f'{{"to":"{target_filter}"}}'
                }
                
                url = f"https://api.trongrid.io/v1/contracts/{contract_hex}/events"
                async with http_client.get(url, params=params) as resp:
                    data = await resp.json()
                    events = data.get("data", [])
                    
                    for evt in events:
                        # Each event includes details; 'result' holds decoded fields
                        to_addr = evt["result"]["to"]   # Tron address (base58)
                        from_addr = evt["result"]["from"]  # Tron address (base58)
                        value = evt["result"]["value"]  # string value of USDT (in smallest units)
                        
                        # Verify this is a transfer to our monitored address
                        if to_addr == tron_receiver:
                            # USDT has 6 decimals on Tron
                            amount = int(value)
                            
                            log_message(f"USDT Transfer detected to {tron_receiver}")
                            log_message(f"From: {from_addr}")
                            log_message(f"Amount: {amount/1_000_000} USDT")
                            
                            # Update the cumulative claim
                            current_claim += amount
                            
                            # Update the claim on Ethereum
                            await update_claim_on_eth(receiver_hex, current_claim)
                    
                    # Update last_timestamp for next poll (use last event's timestamp + 1)
                    if events:
                        last_timestamp = events[-1]["block_timestamp"] + 1
                    
                    # Check if there are more pages to fetch
                    fingerprint = data.get("meta", {}).get("fingerprint")
                    while fingerprint:
                        params["fingerprint"] = fingerprint
                        async with http_client.get(url, params=params) as resp:
                            data = await resp.json()
                            events = data.get("data", [])
                            
                            for evt in events:
                                to_addr = evt["result"]["to"]
                                from_addr = evt["result"]["from"]
                                value = evt["result"]["value"]
                                
                                if to_addr == tron_receiver:
                                    amount = int(value)
                                    log_message(f"USDT Transfer detected to {tron_receiver}")
                                    log_message(f"From: {from_addr}")
                                    log_message(f"Amount: {amount/1_000_000} USDT")
                                    
                                    current_claim += amount
                                    await update_claim_on_eth(receiver_hex, current_claim)
                            
                            if events:
                                last_timestamp = events[-1]["block_timestamp"] + 1
                            
                            fingerprint = data.get("meta", {}).get("fingerprint")
                
                # Wait before checking for new events
                await asyncio.sleep(3)  # Poll every 3 seconds (Tron block time)
                
            except Exception as e:
                log_message(f"Error in Tron event polling: {e}")
                await asyncio.sleep(5)  # Wait longer on error
                
    except asyncio.CancelledError:
        log_message(f"Tron listener for {tron_receiver} was cancelled")
    except Exception as e:
        log_message(f"Error in Tron listener for {tron_receiver}: {e}")
    finally:
        # Close the session when the listener is done
        if http_client:
            await http_client.close()
            http_client = None

# Mock Tron Transfers
async def mock_tron_transfers(receiver_hex, tron_receiver):
    """Simulate Tron USDT transfers without actually sending transactions on the Tron chain"""
    log_message(f"Starting mock Tron USDT transfers for: {tron_receiver}")
    
    try:
        # Get the order details from active_orders
        if receiver_hex not in active_orders:
            log_message(f"Error: No active order found for receiver {receiver_hex}")
            return
        
        order = active_orders[receiver_hex]['order']
        total_amount = order['amount']
        
        # Calculate the amount per transfer (divide total by number of transfers)
        amount_per_transfer = total_amount // MOCK_TRANSFER_COUNT
        # Handle any remainder in the last transfer
        remainder = total_amount % MOCK_TRANSFER_COUNT
        
        log_message(f"Total amount to simulate: {total_amount/1_000_000} USDT")
        log_message(f"Will simulate {MOCK_TRANSFER_COUNT} transfers of {amount_per_transfer/1_000_000} USDT each")
        if remainder > 0:
            log_message(f"Last transfer will include an additional {remainder/1_000_000} USDT")
        
        current_claim = 0
        
        # Simulate transfers
        for i in range(MOCK_TRANSFER_COUNT):
            # Calculate the amount for this transfer
            transfer_amount = amount_per_transfer
            if i == MOCK_TRANSFER_COUNT - 1 and remainder > 0:
                # Add remainder to the last transfer
                transfer_amount += remainder
            
            # Update the cumulative claim
            current_claim += transfer_amount
            
            # Log the mock transfer
            log_message(f"Mock USDT Transfer #{i+1}/{MOCK_TRANSFER_COUNT} to {tron_receiver}")
            log_message(f"Amount: {transfer_amount/1_000_000} USDT")
            log_message(f"Cumulative claim: {current_claim/1_000_000} USDT")
            
            # Update the claim on Ethereum
            await update_claim_on_eth(receiver_hex, current_claim)
            
            # Wait before the next mock transfer
            if i < MOCK_TRANSFER_COUNT - 1:  # Don't wait after the last transfer
                log_message(f"Waiting {MOCK_TRANSFER_DELAY} seconds before next mock transfer...")
                await asyncio.sleep(MOCK_TRANSFER_DELAY)
        
        log_message(f"All mock transfers completed for {tron_receiver}")
        
    except asyncio.CancelledError:
        log_message(f"Mock Tron listener for {tron_receiver} was cancelled")
    except Exception as e:
        log_message(f"Error in mock Tron listener for {tron_receiver}: {e}")

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
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        log_message(f"Claim update transaction sent: {tx_hash.hex()}")
        
        # Wait for transaction to be mined
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if receipt.status == 1:
            log_message(f"Claim update successful: {claim_amount}")
            # Update our local tracking
            if receiver_hex in active_orders:
                active_orders[receiver_hex]['claim'] = claim_amount
        else:
            log_message(f"Claim update failed: {receipt}")
    except Exception as e:
        log_message(f"Error updating claim: {e}")

# Main function
async def main():
    """Main entry point for the relayer"""
    log_message("Starting UntronV2 Relayer...")
    log_message(f"Ethereum Node: {ETH_NODE}")
    log_message(f"Contract Address: {CONTRACT_ADDRESS}")
    log_message(f"LP Address: {account.address}")
    
    try:
        # Start the Ethereum event listeners
        await asyncio.gather(
            listen_for_order_created(),
            listen_for_order_closed()
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
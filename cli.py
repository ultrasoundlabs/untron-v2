#!/usr/bin/env python3
import json
import argparse
import sys
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_utils import to_checksum_address
import os
from dotenv import load_dotenv
import base58

# Load environment variables from .env file
load_dotenv()

def base58_to_bytes(base58_addr):
    """Convert base58check encoded Tron address to bytes20 format for contract"""
    # Decode base58 address
    decoded = base58.b58decode(base58_addr)
    # Remove the 0x41 prefix and checksum
    return decoded[1:-4]

def bytes_to_base58(bytes_addr):
    """Convert bytes20 format from contract to base58check encoded Tron address"""
    # Add the 0x41 prefix and calculate checksum
    addr_with_prefix = b'\x41' + bytes_addr
    # Calculate checksum (double SHA256, take first 4 bytes)
    checksum = Web3.keccak(Web3.keccak(addr_with_prefix))[:4]
    # Combine and encode
    return base58.b58encode(addr_with_prefix + checksum).decode('utf-8')

class UntronV2CLI:
    def __init__(self, rpc_url=None, contract_address=None, private_key=None):
        # Set default values or use provided values
        self.rpc_url = rpc_url or os.getenv('RPC_URL')
        self.contract_address = contract_address or os.getenv('CONTRACT_ADDRESS')
        self.private_key = private_key or os.getenv('PRIVATE_KEY')
        
        if not all([self.rpc_url, self.contract_address, self.private_key]):
            print("Error: Missing required parameters. Please provide RPC_URL, CONTRACT_ADDRESS, and PRIVATE_KEY")
            print("Either as arguments or in a .env file")
            sys.exit(1)
        
        # Load contract ABI from the embedded JSON
        self.abi = self.load_abi()
        
        # Connect to the blockchain
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        # Add middleware for POA networks like BNB Chain, Polygon, etc.
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        # Check connection
        if not self.w3.is_connected():
            print(f"Error: Could not connect to RPC at {self.rpc_url}")
            sys.exit(1)
            
        # Set up account from private key
        self.account = self.w3.eth.account.from_key(self.private_key)
        self.address = self.account.address
        
        # Create contract instance
        self.contract = self.w3.eth.contract(
            address=to_checksum_address(self.contract_address),
            abi=self.abi
        )
        
        print(f"Connected to blockchain at {self.rpc_url}")
        print(f"Using account: {self.address}")
        print(f"Contract address: {self.contract_address}")
    
    def load_abi(self):
        return json.load(open("out/UntronV2.json"))["abi"]

    def _build_tx(self, function, *args, **kwargs):
        """Build a transaction with appropriate gas settings"""
        try:
            # Get the contract function
            func = getattr(self.contract.functions, function)
            
            # Get transaction parameters
            nonce = self.w3.eth.get_transaction_count(self.address)
            
            # Get current base fee and add a buffer
            base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = self.w3.eth.max_priority_fee
            # Add 20% buffer to base fee to account for potential increases
            max_fee_per_gas = int(base_fee * 1.2) + max_priority_fee
            
            # Build the transaction
            tx = func(*args).build_transaction({
                'from': self.address,
                'nonce': nonce,
                'gas': kwargs.get('gas', 2000000),  # Default gas limit
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'value': kwargs.get('value', 0)  # ETH value to send
            })
            
            return tx
        except Exception as e:
            print(f"Error building transaction: {e}")
            return None

    def _send_tx(self, tx):
        """Sign and send a transaction"""
        try:
            # Sign the transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            
            # Send the transaction
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for the transaction receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            print(f"Transaction successful! Hash: {tx_hash.hex()}")
            print(f"Gas used: {receipt['gasUsed']}")
            
            return receipt
        except Exception as e:
            print(f"Error sending transaction: {e}")
            return None

    def _call_function(self, function, *args):
        """Call a read-only function"""
        try:
            func = getattr(self.contract.functions, function)
            result = func(*args).call()
            return result
        except Exception as e:
            print(f"Error calling function: {e}")
            return None

    # Write functions
    def set_order_creator(self, creator, allowed):
        """Set an address as an allowed order creator"""
        tx = self._build_tx("setOrderCreator", to_checksum_address(creator), allowed)
        if tx:
            return self._send_tx(tx)
        return None

    def set_order_duration(self, duration):
        """Set the order duration"""
        tx = self._build_tx("setOrderDuration", int(duration))
        if tx:
            return self._send_tx(tx)
        return None

    def set_prover(self, prover):
        """Set the prover address"""
        tx = self._build_tx("setProver", to_checksum_address(prover))
        if tx:
            return self._send_tx(tx)
        return None

    def deposit(self, amount, rate):
        """Deposit funds into the contract"""
        tx = self._build_tx("deposit", int(amount), int(rate))
        if tx:
            return self._send_tx(tx)
        return None

    def withdraw(self, amount):
        """Withdraw funds from the contract"""
        tx = self._build_tx("withdraw", int(amount))
        if tx:
            return self._send_tx(tx)
        return None

    def set_receivers(self, receivers):
        """Set receivers for the caller"""
        # Convert base58check receivers to bytes20 format
        bytes_receivers = [base58_to_bytes(r) for r in receivers]
        tx = self._build_tx("setReceivers", bytes_receivers)
        if tx:
            return self._send_tx(tx)
        return None

    def remove_receivers(self, receivers):
        """Remove receivers for the caller"""
        # Convert base58check receivers to bytes20 format
        bytes_receivers = [base58_to_bytes(r) for r in receivers]
        tx = self._build_tx("removeReceivers", bytes_receivers)
        if tx:
            return self._send_tx(tx)
        return None

    def create_order(self, receiver, amount, rate, beneficiary):
        """Create a new order"""
        bytes_receiver = base58_to_bytes(receiver)
        tx = self._build_tx("createOrder", bytes_receiver, int(amount), int(rate), to_checksum_address(beneficiary))
        if tx:
            return self._send_tx(tx)
        return None

    def set_claim(self, receiver, amount):
        """Set a claim for a receiver"""
        bytes_receiver = base58_to_bytes(receiver)
        tx = self._build_tx("setClaim", bytes_receiver, int(amount))
        if tx:
            return self._send_tx(tx)
        return None

    def prove_claim(self, receiver, at_amount, proof):
        """Prove a claim with a proof"""
        bytes_receiver = base58_to_bytes(receiver)
        bytes_proof = bytes.fromhex(proof.replace('0x', ''))
        tx = self._build_tx("proveClaim", bytes_receiver, int(at_amount), bytes_proof)
        if tx:
            return self._send_tx(tx)
        return None

    # Read functions
    def get_allowed_order_creators(self, address):
        """Check if an address is an allowed order creator"""
        result = self._call_function("allowedOrderCreators", to_checksum_address(address))
        print(f"Is allowed order creator: {result}")
        return result

    def get_order_duration(self):
        """Get the current order duration"""
        result = self._call_function("orderDuration")
        print(f"Order duration: {result}")
        return result

    def get_prover(self):
        """Get the current prover address"""
        result = self._call_function("prover")
        print(f"Prover address: {result}")
        return result

    def get_liquidity_provider(self, address):
        """Get liquidity provider information"""
        result = self._call_function("liquidityProviders", to_checksum_address(address))
        if result:
            print(f"Liquidity provider {address}:")
            print(f"  Available: {result[0]}")
            print(f"  Rate: {result[1]}")
        return result

    def get_receiver(self, receiver):
        """Get receiver information"""
        bytes_receiver = base58_to_bytes(receiver)
        result = self._call_function("receivers", bytes_receiver)
        if result:
            print(f"Receiver {receiver}:")
            print(f"  Owner: {result[0]}")
            print("  Order:")
            print(f"    Creator: {result[1][0]}")
            print(f"    Amount: {result[1][1]}")
            print(f"    Rate: {result[1][2]}")
            print(f"    Timestamp: {result[1][3]}")
            print(f"    Beneficiary: {result[1][4]}")
            print(f"    Creator Claim: {result[1][5][0]}")
            print(f"    LP Claim: {result[1][5][1]}")
        return result

def main():
    parser = argparse.ArgumentParser(description='UntronV2 Contract CLI')
    
    # Global arguments
    parser.add_argument('--rpc', help='RPC URL')
    parser.add_argument('--contract', help='Contract address')
    parser.add_argument('--private-key', help='Private key for transactions')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Read function subparsers
    parser_allowed_creators = subparsers.add_parser('check-creator', help='Check if address is an allowed order creator')
    parser_allowed_creators.add_argument('address', help='Address to check')
    
    subparsers.add_parser('get-duration', help='Get order duration')
    
    subparsers.add_parser('get-prover', help='Get prover address')
    
    parser_lp = subparsers.add_parser('get-lp', help='Get liquidity provider info')
    parser_lp.add_argument('address', help='Liquidity provider address')
    
    parser_receiver = subparsers.add_parser('get-receiver', help='Get receiver info')
    parser_receiver.add_argument('receiver', help='Receiver ID (base58check encoded Tron address)')
    
    # Write function subparsers
    parser_set_creator = subparsers.add_parser('set-creator', help='Set allowed order creator')
    parser_set_creator.add_argument('creator', help='Creator address')
    parser_set_creator.add_argument('allowed', type=bool, help='Allow status (true/false)')
    
    parser_set_duration = subparsers.add_parser('set-duration', help='Set order duration')
    parser_set_duration.add_argument('duration', type=int, help='Duration in seconds')
    
    parser_set_prover = subparsers.add_parser('set-prover', help='Set prover address')
    parser_set_prover.add_argument('prover', help='Prover address')
    
    parser_deposit = subparsers.add_parser('deposit', help='Deposit funds')
    parser_deposit.add_argument('amount', type=int, help='Amount to deposit')
    parser_deposit.add_argument('rate', type=int, help='Rate to set')
    
    parser_withdraw = subparsers.add_parser('withdraw', help='Withdraw funds')
    parser_withdraw.add_argument('amount', type=int, help='Amount to withdraw')
    
    parser_set_receivers = subparsers.add_parser('set-receivers', help='Set receivers')
    parser_set_receivers.add_argument('receivers', nargs='+', help='List of receiver IDs (base58check encoded Tron addresses)')
    
    parser_remove_receivers = subparsers.add_parser('remove-receivers', help='Remove receivers')
    parser_remove_receivers.add_argument('receivers', nargs='+', help='List of receiver IDs (base58check encoded Tron addresses)')
    
    parser_create_order = subparsers.add_parser('create-order', help='Create a new order')
    parser_create_order.add_argument('receiver', help='Receiver ID (base58check encoded Tron address)')
    parser_create_order.add_argument('amount', type=int, help='Order amount')
    parser_create_order.add_argument('rate', type=int, help='Order rate')
    parser_create_order.add_argument('beneficiary', help='Beneficiary address')
    
    parser_set_claim = subparsers.add_parser('set-claim', help='Set a claim')
    parser_set_claim.add_argument('receiver', help='Receiver ID (base58check encoded Tron address)')
    parser_set_claim.add_argument('amount', type=int, help='Claim amount')
    
    parser_prove_claim = subparsers.add_parser('prove-claim', help='Prove a claim')
    parser_prove_claim.add_argument('receiver', help='Receiver ID (base58check encoded Tron address)')
    parser_prove_claim.add_argument('amount', type=int, help='Claim amount')
    parser_prove_claim.add_argument('proof', help='Proof data (hex)')
    
    args = parser.parse_args()
    
    # If no arguments provided, show help
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    # Initialize the CLI
    cli = UntronV2CLI(
        rpc_url=args.rpc,
        contract_address=args.contract,
        private_key=args.private_key
    )
    
    # Execute the appropriate command
    if args.command == 'check-creator':
        cli.get_allowed_order_creators(args.address)
    elif args.command == 'get-duration':
        cli.get_order_duration()
    elif args.command == 'get-prover':
        cli.get_prover()
    elif args.command == 'get-lp':
        cli.get_liquidity_provider(args.address)
    elif args.command == 'get-receiver':
        cli.get_receiver(args.receiver)
    elif args.command == 'set-creator':
        cli.set_order_creator(args.creator, args.allowed)
    elif args.command == 'set-duration':
        cli.set_order_duration(args.duration)
    elif args.command == 'set-prover':
        cli.set_prover(args.prover)
    elif args.command == 'deposit':
        cli.deposit(args.amount, args.rate)
    elif args.command == 'withdraw':
        cli.withdraw(args.amount)
    elif args.command == 'set-receivers':
        cli.set_receivers(args.receivers)
    elif args.command == 'remove-receivers':
        cli.remove_receivers(args.receivers)
    elif args.command == 'create-order':
        cli.create_order(args.receiver, args.amount, args.rate, args.beneficiary)
    elif args.command == 'set-claim':
        cli.set_claim(args.receiver, args.amount)
    elif args.command == 'prove-claim':
        cli.prove_claim(args.receiver, args.amount, args.proof)
    else:
        print("Invalid command")
        parser.print_help()

if __name__ == "__main__":
    main()
# pragma version 0.4.0
# @license MIT
# @author Ultrasound Labs

# Untron V2.2: Optimistic Tron<->EVM USDT bridge
# 
# This contract facilitates the transfer of USDT between a deployment chain (e.g., Ethereum)
# and the Tron blockchain. It implements a liquidity pool model where:
# - Liquidity Providers (LPs) lock USDT on the deployment chain
# - Order Creators send Tron USDT to LPs' Tron addresses
# - In return, LPs' locked USDT is sent to Order Creators' 
#   specified "beneficiaries" on the deployment chain
#
# Dependencies:
# - snekmate/auth: For ownership management
# - IERC20: For USDT token interactions
# - IProver: For ZK-based cross-chain transfer verification
#
# V2.2 is a fork of V2.0 that makes the contract more ergonomic.

# Imports
from lib.github.pcaversaccio.snekmate.src.snekmate.auth import ownable
from ethereum.ercs import IERC20

# Initialize ownable module for access control
initializes: ownable
exports: ownable.transfer_ownership

# Events
# Events are emitted for all significant state changes to simplify off-chain tracking
event OrderCreatorSet:
    creator: indexed(address)  # Address being granted/revoked order creation rights
    allowed: bool     # Whether the address is being allowed or disallowed

event OrderDurationSet:
    duration: uint256  # New duration in seconds for order expiration

event ProverSet:
    prover: IProver    # New prover contract address for dispute resolution

event Deposited:
    provider: indexed(address)  # LP address making the deposit
    amount: uint256    # Amount of USDT deposited
    rate: uint256      # Exchange rate set by LP (in basis points, e.g., 990000 = 0.99)

event Withdrawn:
    provider: indexed(address)  # LP address making the withdrawal
    amount: uint256    # Amount of USDT withdrawn

event ReceiversSet:
    provider: indexed(address)  # LP address setting receivers
    receivers: DynArray[bytes20, 1024]  # Array of Tron addresses where LP can receive USDT

event ReceiversRemoved:
    provider: indexed(address)  # LP address removing receivers
    receivers: DynArray[bytes20, 1024]  # Array of Tron addresses being removed

event OrderCreated:
    receiver: indexed(bytes20)    # Tron address where Tron USDT should be sent
    orderNonce: uint256           # Sequential order nonce for this receiver
    lp: indexed(address)          # LP who owns the receiver address
    creator: address              # Address creating the order
    amount: uint256               # Amount of Tron USDT to be sent
    rate: uint256                 # Exchange rate for the order
    timestamp: uint256            # Order creation timestamp
    beneficiary: indexed(address) # Address to receive USDT on deployment chain

event OrderClosed:
    receiver: indexed(bytes20)    # Tron address associated with the closed order
    orderNonce: uint256           # Sequential nonce that identified the order
    lp: indexed(address)          # LP who owns the receiver address
    atAmount: uint256             # Amount of Tron USDT that was actually sent
    beneficiary: indexed(address) # Address that received the USDT on deployment chain

event ClaimUpdated:
    receiver: indexed(bytes20)  # Tron address associated with the order
    orderNonce: uint256         # Sequential nonce that identified the order
    claimer: indexed(address)   # Address updating the claim (Order Creator or LP)
    amount: uint256             # New claim amount
    isCreatorClaim: bool        # Whether this is the creator's claim (true) or LP's claim (false)

# State Variables
# Core contract configuration and state

# USDT contract address on deployment chain (NOT TRON)
# This is the token that LPs lock and Order Creators receive
usdt: immutable(address)

# Access control for order creation
# Only approved addresses can create orders to prevent spam
allowedOrderCreators: public(HashMap[address, bool])

# Time window for order completion
# After this duration, orders can be resolved via ZK proof
orderDuration: public(uint256)

# External contract for verifying cross-chain transfers
# Can be a ZK prover, TEE verifier, or trusted oracle
prover: public(IProver)

# Structs
# Data structures for managing LPs, receivers, and orders

# Liquidity provider information
# Tracks available liquidity and exchange rate
struct LiquidityProvider:
    available: uint256  # Amount of USDT available for orders
    rate: uint256     # Exchange rate in basis points (e.g., 990000 = 0.99)

# Tron address information
# Links Tron addresses to LPs and tracks active orders
struct Receiver:
    owner: address    # LP who owns this Tron address
    order: Order      # Active order using this address, if any

# Order information
# Represents a transfer request from Order Creator to LP
struct Order:
    creator: address  # Address that created the order
    amount: uint256   # Amount of Tron USDT to be sent
    rate: uint256     # Exchange rate for the transfer
    timestamp: uint256  # When the order was created
    beneficiary: address  # Who receives the USDT on deployment chain
    claims: Claims    # Amount claims from both parties
    orderNonce: uint256    # Sequential order nonce for this receiver

# Claims from both parties in an order
# Used to resolve orders either by agreement or dispute
struct Claims:
    creatorClaim: uint256  # Amount Order Creator claims to have sent
    lpClaim: uint256      # Amount LP claims to have received

# Interface for external proof verification
# Used to verify cross-chain transfers in case of disputes
interface IProver:
    def proveClaim(receiver: bytes20, amount: uint256, timestamp: uint256, period: uint256, proof: Bytes[4096]) -> bool: nonpayable

# Main state storage
liquidityProviders: public(HashMap[address, LiquidityProvider])  # LP address -> LP info
receivers: public(HashMap[bytes20, Receiver])  # Tron address -> receiver info
receiverNonces: public(HashMap[bytes20, uint256])  # Tron address -> next order nonce

# Constructor
# Initializes the contract with the USDT token address
@deploy
def __init__(_usdt: address):
    ownable.__init__()
    usdt = _usdt

# Access Control Functions
# Functions for managing contract configuration and permissions

@external
def setOrderCreator(creator: address, allowed: bool):
    """
    Allows or disallows an address to create orders.
    Only callable by the contract owner.
    """
    # Ensure only the contract owner can call this function
    assert msg.sender == ownable.owner
    
    # Update the order creator's permission
    self.allowedOrderCreators[creator] = allowed
    
    # Emit event for off-chain tracking
    log OrderCreatorSet(creator, allowed)

@external
def setOrderDuration(duration: uint256):
    """
    Sets the duration after which orders can be resolved via ZK proof.
    Only callable by the contract owner.
    """
    # Ensure only the contract owner can call this function
    assert msg.sender == ownable.owner
    
    # Update the order duration
    self.orderDuration = duration
    
    # Emit event for off-chain tracking
    log OrderDurationSet(duration)

@external
def setProver(prover: IProver):
    """
    Sets the contract that will verify cross-chain transfers.
    Only callable by the contract owner.
    """
    # Ensure only the contract owner can call this function
    assert msg.sender == ownable.owner
    
    # Update the prover contract address
    self.prover = prover
    
    # Emit event for off-chain tracking
    log ProverSet(prover)

# Liquidity Management Functions
# Functions for LPs to manage their liquidity and receivers

@external
def deposit(amount: uint256, rate: uint256):
    """
    Allows LPs to deposit USDT and set their exchange rate.
    Transfers USDT from LP to contract and updates LP info.
    """
    # Transfer USDT from LP to contract using ERC20 transferFrom
    # This requires the LP to have approved the contract to spend their USDT
    extcall IERC20(usdt).transferFrom(msg.sender, self, amount)
    
    # Update the LP's information in the contract
    self.liquidityProviders[msg.sender].available += amount  # Add to available liquidity
    self.liquidityProviders[msg.sender].rate = rate          # Set their exchange rate
    
    # Emit event for off-chain tracking
    log Deposited(msg.sender, amount, rate)

@external
def withdraw(amount: uint256):
    """
    Allows LPs to withdraw their USDT liquidity.
    """
    # Ensure LP has enough available liquidity to withdraw
    assert amount <= self.liquidityProviders[msg.sender].available
    
    # Transfer USDT from contract to LP using ERC20 transfer
    extcall IERC20(usdt).transfer(msg.sender, amount)
    
    # Update LP's available balance
    self.liquidityProviders[msg.sender].available -= amount

    # Emit event for off-chain tracking
    log Withdrawn(msg.sender, amount)

@external
def setReceivers(receivers: DynArray[bytes20, 1024]):
    """
    Allows LPs to register Tron addresses where they can receive USDT.
    Each address must not already be registered.
    """
    # Loop through each provided Tron address
    for receiver: bytes20 in receivers:
        # Ensure the address isn't already registered to someone else
        # empty(address) means no owner, so it's available
        assert self.receivers[receiver].owner == empty(address)
        
        # Register the address to the calling LP
        self.receivers[receiver].owner = msg.sender
    
    # Emit event for off-chain tracking
    log ReceiversSet(msg.sender, receivers)

@external
def removeReceivers(receivers: DynArray[bytes20, 1024]):
    """
    Allows LPs to remove their registered Tron addresses.
    Each address must be owned by the caller.
    """
    # Loop through each provided Tron address
    for receiver: bytes20 in receivers:
        # Ensure the caller owns this address
        assert self.receivers[receiver].owner == msg.sender
        
        # Remove ownership by setting to empty address
        self.receivers[receiver].owner = empty(address)
    
    # Emit event for off-chain tracking
    log ReceiversRemoved(msg.sender, receivers)

# Order Management Functions
# Functions for creating and resolving orders

@external
def createOrder(receiver: bytes20, amount: uint256, rate: uint256, beneficiary: address):
    """
    Creates a new order for transferring Tron USDT.
    Requires:
    - Caller is an allowed order creator
    - Receiver address is available
    - LP has sufficient liquidity
    - Rate matches LP's rate
    """
    # Verify caller has permission to create orders
    assert self.allowedOrderCreators[msg.sender], "unauthorized"
    
    # Ensure the receiver address isn't already being used in an active order
    assert self.receivers[receiver].order.creator == empty(address), "receiver busy"
    
    # Get the LP who owns this receiver address
    lp: address = self.receivers[receiver].owner
    
    # Calculate how much USDT the LP will receive on the deployment chain
    # Rate is in basis points (e.g., 990000 = 0.99)
    amountReceived: uint256 = amount * rate // 1000000

    # Validate the order parameters
    assert amountReceived > 0, "too small amount received"  # Prevent zero-value orders
    assert self.liquidityProviders[lp].available >= amountReceived, "not enough liquidity"  # Check LP has enough liquidity
    assert rate == self.liquidityProviders[lp].rate, "rate mismatch"  # Ensure specified rate matches LP's set rate

    # Lock the LP's USDT for this order
    self.liquidityProviders[lp].available -= amountReceived
    
    # Initialize the claims structure - creator claims full amount, LP starts at 0
    claims: Claims = Claims(
        creatorClaim=amount,  # Order creator claims they'll send full amount
        lpClaim=0            # LP starts with no claim (no USDT received yet)
    )
    
    # Assign sequential nonce for this receiver
    orderNonce: uint256 = self.receiverNonces[receiver]
    self.receiverNonces[receiver] = orderNonce + 1

    # Create the order structure with all necessary information
    order: Order = Order(
        creator=msg.sender,           # Who created the order
        amount=amount,                # How much Tron USDT to send
        rate=rate,                    # Exchange rate for the transfer
        timestamp=block.timestamp,    # When the order was created
        beneficiary=beneficiary,      # Who gets the USDT on deployment chain
        claims=claims,                # Initial claims from both parties
        orderNonce=orderNonce         # Sequential nonce for this receiver
    )
    
    # Store the order in the receiver's data
    self.receivers[receiver].order = order
    
    # Emit event for off-chain tracking
    log OrderCreated(receiver, orderNonce, lp, msg.sender, amount, order.rate, order.timestamp, beneficiary)

@external
def setClaim(receiver: bytes20, amount: uint256):
    """
    Allows Order Creator or LP to set their claim amount.
    If both claims match, the order is automatically closed.
    """
    orderNonce: uint256 = self.receivers[receiver].order.orderNonce  # Load order nonce once
    if self.receivers[receiver].order.creator == msg.sender:
        self.receivers[receiver].order.claims.creatorClaim = amount
        log ClaimUpdated(receiver, orderNonce, msg.sender, amount, True)
    if self.receivers[receiver].owner == msg.sender:
        self.receivers[receiver].order.claims.lpClaim = amount
        log ClaimUpdated(receiver, orderNonce, msg.sender, amount, False)
    
    creatorClaim: uint256 = self.receivers[receiver].order.claims.creatorClaim
    lpClaim: uint256 = self.receivers[receiver].order.claims.lpClaim

    if creatorClaim == lpClaim:
        self.closeOrder(receiver, creatorClaim)

@internal
def closeOrder(receiver: bytes20, atAmount: uint256):
    """
    Internal function to close an order and distribute funds.
    Calculates:
    - Amount to send to beneficiary (surrenderAmount)
    - Amount to return to LP (reimbursementAmount)
    """
    # Load the nonce associated with this order
    orderNonce: uint256 = self.receivers[receiver].order.orderNonce
    # Ensure that the order is not already closed
    assert self.receivers[receiver].order.creator != empty(address), "order already closed"

    # Get the original order parameters
    orderAmount: uint256 = self.receivers[receiver].order.amount  # Original amount requested
    orderRate: uint256 = self.receivers[receiver].order.rate      # Original exchange rate

    # Calculate how much USDT to return to the LP
    # This is the difference between what was requested and what was actually sent
    # Multiplied by the exchange rate to convert to deployment chain USDT
    reimbursementAmount: uint256 = (
            orderAmount - min(atAmount, orderAmount)  # Difference between requested and actual
        ) * orderRate // 1000000                      # Convert to deployment chain USDT
    
    # Calculate how much USDT to send to the beneficiary
    # This is the minimum of what was requested and what was actually sent
    # multiplied by the exchange rate to convert to deployment chain USDT
    surrenderAmount: uint256 = min(
            atAmount,                                  # Amount actually sent
            orderAmount                                # Amount originally requested
        ) * orderRate // 1000000                      # Convert to deployment chain USDT
    
    # Get the beneficiary address from the order
    beneficiary: address = self.receivers[receiver].order.beneficiary
    
    # If there's an amount to send to the beneficiary, transfer it
    if surrenderAmount > 0:
        extcall IERC20(usdt).transfer(beneficiary, surrenderAmount)  # Transfer USDT to beneficiary
    
    # Get the LP's address and return any unused liquidity
    lp: address = self.receivers[receiver].owner
    self.liquidityProviders[lp].available += reimbursementAmount  # Return unused USDT to LP

    # Clear the order by setting creator to empty address
    # This marks the receiver as available for new orders
    self.receivers[receiver].order.creator = empty(address)

    # Emit event for off-chain tracking
    log OrderClosed(receiver, orderNonce, lp, atAmount, beneficiary)

@external
def proveClaim(receiver: bytes20, atAmount: uint256, proof: Bytes[4096]):
    """
    Allows resolution of an expired order using ZK proof.
    Verifies the proof using the prover contract and closes the order.
    """
    # Check if the order has expired (current time > order creation time + duration)
    assert self.receivers[receiver].order.timestamp + self.orderDuration < block.timestamp, "not expired yet"

    # Verify the ZK proof using the prover contract
    # This proves that the specified amount of Tron USDT was sent to the receiver
    assert extcall self.prover.proveClaim(
        receiver,                                    # Tron address that received USDT
        atAmount,                                   # Amount of USDT that was sent
        self.receivers[receiver].order.timestamp,   # When the order was created
        self.orderDuration,                         # How long the order was valid for
        proof                                       # The ZK proof of the transfer
    ), "proving failed"

    # If proof is valid, close the order and distribute funds
    self.closeOrder(receiver, atAmount)
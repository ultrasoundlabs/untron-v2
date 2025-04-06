# pragma version 0.4.0
# @license MIT
# @author Ultrasound Labs

# MockProver: A mock implementation of IProver that uses owner signatures as proofs
# This contract is used for testing and development purposes only

# Imports
from lib.github.pcaversaccio.snekmate.src.snekmate.auth import ownable

# Initialize ownable module for access control
initializes: ownable

# Events
event ProofVerified:
    receiver: bytes20  # Tron address that received USDT
    amount: uint256    # Amount of USDT that was sent
    timestamp: uint256 # When the order was created
    period: uint256    # How long the order was valid for

# Constructor
@deploy
def __init__():
    ownable.__init__()

@external
def proveClaim(receiver: bytes20, amount: uint256, timestamp: uint256, period: uint256, proof: Bytes[4096]) -> bool:
    """
    Verifies a proof by checking if it's a valid signature from the owner.
    The proof should be a signature of the concatenated parameters.
    """
    # The proof should be a signature of the concatenated parameters
    # We expect the proof to be a 65-byte signature (r, s, v)
    assert len(proof) == 65, "invalid signature length"
    
    # Create the message hash by concatenating the parameters and hashing
    message: bytes32 = keccak256(
        concat(
            concat(
                concat(
                    convert(receiver, bytes32),
                    convert(amount, bytes32)
                ),
                convert(timestamp, bytes32)
            ),
            convert(period, bytes32)
        )
    )
    
    # Extract r, s, v from the signature
    r: bytes32 = extract32(proof, 0)
    s: bytes32 = extract32(proof, 32)
    v: uint256 = convert(slice(proof, 64, 1), uint256)
    
    # Recover the signer's address
    signer: address = ecrecover(message, v, r, s)
    
    # Verify the signer is the owner
    assert signer == ownable.owner, "invalid signature"
    
    # Emit event for off-chain tracking
    log ProofVerified(receiver, amount, timestamp, period)
    
    return True 
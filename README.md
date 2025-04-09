# untron-v2
Efficiency-centric alternative to Untron V1, a P2P swapper from Tron

## Overview

Untron V2 is a B2B P2P marketplace for exchanging USDT on Tron Network into EVM networks, [inspired by ZKP2P](https://zkp2p.xyz). Ethereum-based projects, such as wallets, who are willing to enable Tron USDT deposits, can integrate Untron V2 and create swap orders on behalf of their users.

The primary difference between Untron V1 and Untron V2 is the introduction of claims architecture. In short, V2 requires each LP to actively listen for orders and deposits using the relayer software (e.g. run on a VPS). V1, in turn, relied on the ZKP relayer as the only source of truth, which allowed all LPs to passively act as liquidity providers and just rebalance liquidity between chains when needed (similar to ZKP2P).

Even though this makes liquidity provision more complex and thus less attractive, it allows for a more fast and liquidity-efficient resolution of orders with no need for ZKPs for every order. In Untron V2, the ZK engine is only used for order disputes. V2 is also written in Vyper, unlike V1, which was written in Solidity. Everything else is roughly speaking the same.

## Claims Architecture

Each order has two claims:
- creatorClaim: Amount the Order Creator claims to have sent in Tron USDT
- lpClaim: Amount the LP claims to have received in Tron USDT

Claims can be updated independently by each party up to the original order amount. Orders close automatically when claims match, avoiding the need for ZKPs.

If claims don't match:
1. Either party can submit a ZK proof after order expiration
2. Parties can continue updating claims until agreement

On order closure (via matching claims or ZK proof):
- surrenderAmount = min(creatorClaim, lpClaim) sent to beneficiary
- reimbursementAmount = unused liquidity returned to LP
- Order marked closed and receiver freed

This enables efficient resolution for cooperative parties while maintaining security through Untron's ZK engine when needed.

_This entire section just read was written by an AI but it's fully correct I swear — Alex Hook_

## Visual Overview

```mermaid
flowchart TD
    Start([Start]) --> CreateOrder[Order Creator creates order]
    
    subgraph "Order Creation Phase"
        CreateOrder --> LockFunds[LP's USDT locked on deployment chain]
        LockFunds --> OrderActive[Order becomes active]
    end
    
    subgraph "Transfer Phase"
        OrderActive --> SendTronUSDT[Order Creator sends Tron USDT to LP's Tron address]
        SendTronUSDT --> UpdateClaims[Both parties can update their claims]
        
        UpdateClaims --> CreatorUpdatesClaim[Order Creator updates creatorClaim]
        UpdateClaims --> LPUpdatesClaim[LP updates lpClaim]
    end
    
    subgraph "Resolution Phase"
        CreatorUpdatesClaim --> CheckClaimsMatch{Do claims match?}
        LPUpdatesClaim --> CheckClaimsMatch
        
        CheckClaimsMatch -->|Yes| OptimisticResolution[Optimistic Resolution]
        CheckClaimsMatch -->|No| WaitForExpiration[Wait for order expiration]
        
        OptimisticResolution --> CloseOrder[Close order with agreed amount]
        
        WaitForExpiration --> OrderExpired{Order expired?}
        OrderExpired -->|No| UpdateClaims
        OrderExpired -->|Yes| DisputeResolution[Dispute Resolution Options]
        
        DisputeResolution --> ZKProof[Submit ZK proof]
        DisputeResolution --> ContinueNegotiating[Continue updating claims]
        
        ZKProof --> VerifyProof{Is proof valid?}
        VerifyProof -->|Yes| CloseOrder
        VerifyProof -->|No| ProofFailed[Proof verification failed]
        
        ContinueNegotiating --> CheckClaimsMatch
    end
    
    subgraph "Order Closure"
        CloseOrder --> CalculateSurrenderAmount[Calculate amount to send beneficiary]
        CalculateSurrenderAmount --> CalculateReimbursement[Calculate amount to return to LP]
        CalculateReimbursement --> TransferToBeneficiary[Transfer USDT to beneficiary]
        TransferToBeneficiary --> ReturnUnusedLiquidity[Return unused liquidity to LP]
        ReturnUnusedLiquidity --> ClearOrder[Clear order data]
        ClearOrder --> EmitEvent[Emit OrderClosed event]
        EmitEvent --> End([End])
    end
    
    ProofFailed --> End
    
    %% Edge Cases
    CreateOrder --> InsufficientLiquidity{LP has enough liquidity?}
    InsufficientLiquidity -->|No| FailCreation[Order creation fails]
    InsufficientLiquidity -->|Yes| LockFunds
    
    CreateOrder --> ReceiverBusy{Receiver address available?}
    ReceiverBusy -->|No| FailCreation
    ReceiverBusy -->|Yes| LockFunds
    
    CreateOrder --> RateMismatch{Rate matches LP's rate?}
    RateMismatch -->|No| FailCreation
    RateMismatch -->|Yes| LockFunds
    
    SendTronUSDT --> PartialSend{Full amount sent?}
    PartialSend -->|Yes| UpdateClaims
    PartialSend -->|No| UpdateWithPartialAmount[Update claims with partial amount]
    UpdateWithPartialAmount --> UpdateClaims
    
    SendTronUSDT --> NoSend{Nothing sent?}
    NoSend -->|Yes| UpdateWithZero[Update claims with zero]
    NoSend -->|No| UpdateClaims
    UpdateWithZero --> UpdateClaims
    
    FailCreation --> End
    
    %% Styling
    classDef process fill:#f9f,stroke:#333,stroke-width:1px;
    classDef decision fill:#bbf,stroke:#333,stroke-width:1px;
    classDef endpoint fill:#9f9,stroke:#333,stroke-width:1px;
    classDef failpoint fill:#f99,stroke:#333,stroke-width:1px;
    
    class Start,End endpoint;
    class CheckClaimsMatch,OrderExpired,VerifyProof,InsufficientLiquidity,ReceiverBusy,RateMismatch,PartialSend,NoSend decision;
    class CreateOrder,LockFunds,OrderActive,SendTronUSDT,UpdateClaims,OptimisticResolution,CloseOrder,ZKProof,CalculateSurrenderAmount,CalculateReimbursement,TransferToBeneficiary,ReturnUnusedLiquidity,ClearOrder,EmitEvent,CreatorUpdatesClaim,LPUpdatesClaim,ContinueNegotiating,WaitForExpiration,UpdateWithPartialAmount,UpdateWithZero process;
    class FailCreation,ProofFailed failpoint;
```

## Integrate

For integration, please proceed to [our documentation](https://ultrasoundlabs.github.io/untron-docs). You can also contact us at [contact@untron.finance](mailto:contact@untron.finance), [X account](https://x.com/untronfi), or [Telegram chat](https://t.me/untronchat).
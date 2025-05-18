from src import UntronV2_1
import boa

def moccasin_main():
    contract = UntronV2_1.deploy("0x01bFF41798a0BcF287b996046Ca68b395DbC1071")
    contract.setOrderCreator(boa.env.eoa, True)
    contract.setOrderCreator("0xf178905915f55dd34Ba1980942354dc64109118F", True)
    contract.setOrderCreator("0xEfB9d01CE2EEAB3CC874349aEF009398aFf0C3A0", True)

    usdt0oft = "0xF03b4d9AC1D5d1E7c4cEf54C2A313b9fe051A0aD"
    stargate_oft = "0x8EfBdFF3bAe9a3ED3C0ac7aD86BEbF9aEe46086f"

    contract.setChainInfo(1, usdt0oft, 30101, 1000000) # Ethereum L1, 1 USDT fee
    contract.setChainInfo(42161, usdt0oft, 30110, 0) # Arbitrum, 0 fee
    contract.setChainInfo(130, usdt0oft, 30320, 0) # Unichain, 0 fee
    contract.setChainInfo(57073, usdt0oft, 30339, 0) # Ink, 0 fee

    contract.setChainInfo(8453, stargate_oft, 30184, 0) # Base, 0 fee
    contract.setChainInfo(480, stargate_oft, 30319, 0) # World Chain, 0 fee
    contract.setChainInfo(1923, stargate_oft, 30335, 0) # Base, 0 fee
    contract.setChainInfo(1868, stargate_oft, 30340, 0) # Soneium, 0 fee
    contract.setChainInfo(34443, stargate_oft, 30260, 0) # Mode, 0 fee
    contract.setChainInfo(1135, stargate_oft, 30321, 0) # Lisk, 0 fee

    contract.transfer_ownership("0xf178905915f55dd34Ba1980942354dc64109118F")

    return contract


if __name__ == "__main__":
    moccasin_main()
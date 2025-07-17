from src import UntronV2_2
import boa

def moccasin_main():
    contract = UntronV2_2.deploy("0x01bFF41798a0BcF287b996046Ca68b395DbC1071")
    contract.setOrderCreator(boa.env.eoa, True)
    contract.setOrderCreator("0xf178905915f55dd34Ba1980942354dc64109118F", True)
    contract.setOrderCreator("0xEfB9d01CE2EEAB3CC874349aEF009398aFf0C3A0", True)
    return contract


if __name__ == "__main__":
    moccasin_main()
from src import UntronV2
import boa

def moccasin_main():
    contract = UntronV2.deploy("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9")
    contract.setOrderCreator(boa.env.eoa, True)
    contract.setOrderCreator("0xf178905915f55dd34Ba1980942354dc64109118F", True)
    return contract


if __name__ == "__main__":
    moccasin_main()
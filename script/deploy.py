from src import UntronV2
import boa

def moccasin_main():
    contract = UntronV2.deploy("0xd07308A887ffA74b8965C0F26e6E2e70072C97b9")
    contract.setOrderCreator(boa.env.eoa, True)
    return contract


if __name__ == "__main__":
    moccasin_main()
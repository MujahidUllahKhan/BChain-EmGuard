require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  networks: {
    // Local Hardhat network for testing and gas measurement
    hardhat: {
      chainId: 31337,
    },
    // Hyperledger Besu local node (IBFT 2.0)
    besu_local: {
      url: "http://127.0.0.1:8545",
      chainId: 1337,
      accounts: [
        // Replace with your Besu account private keys
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
      ],
    },
    // Besu testnet (configure your endpoint)
    besu_testnet: {
      url: process.env.BESU_RPC_URL || "http://your-besu-node:8545",
      chainId: parseInt(process.env.BESU_CHAIN_ID || "1337"),
      accounts: process.env.DEPLOYER_PRIVATE_KEY
        ? [process.env.DEPLOYER_PRIVATE_KEY]
        : [],
    },
  },
  gasReporter: {
    enabled: true,
    currency: "USD",
    coinmarketcap: process.env.CMC_API_KEY,
    token: "ETH",
  },
  paths: {
    sources:   "./contracts",
    tests:     "./tests",
    cache:     "./cache",
    artifacts: "./artifacts",
  },
};

import smartpy as sp
FA2 = sp.io.import_template("FA2.py")
FA12 = sp.io.import_template("FA1.2.py")

class Governance:
    def isAdministrator(self, sender):
        return sender == self.data.administrator

    def verifyAdministrator(self, sender):
        sp.verify(self.isAdministrator(sender), self.error.notAdmin())

    @sp.entry_point
    def setAdministrator(self, administrator):
        sp.set_type(administrator, sp.TAddress)
        self.verifyAdministrator(sp.sender)
        self.data.administrator = administrator

class Errors:
    def __init__(self):
        self.prefix = "TIOF_" #TIOF - abbreviation from tokenization is our future
    
    def make(self, s): return (self.prefix + s)
    def notRegistered(self):            return self.make("NOT_REGISTERED")
    def notAdmin(self):                 return self.make("NOT_ADMIN")
    def notAdminOrSeller(self):         return self.make("NOT_ADMIN_OR_SELLER")
    def nonExistentMarket(self):        return self.make("NOT_EXISTENT_MARKET")
    def alredyRegisteredMarket(self):   return self.make("ALREADY_REGISTERED")
    def nonExistentSale(self):          return self.make("NOT_EXISTENT_SALE")
    def priceMismatch(self):            return self.make("PRICE_MISMATCH")

# Constants
FA_1_2_TOKEN_TYPE = 0
FA_2_TOKEN_TYPE = 1
TTokenType = sp.TBounded([FA_1_2_TOKEN_TYPE, FA_2_TOKEN_TYPE])


class TransferTokens:
    def transferFA2(self, sender,receiver,amount,tokenAddress,id):
        arg = [
            sp.record(
                from_ = sender,
                txs = [
                    sp.record(
                        to_         = receiver,
                        token_id    = id , 
                        amount      = amount 
                    )
                ]
            )
        ]
        transferHandle = sp.contract(
            sp.TList(sp.TRecord(from_=sp.TAddress, txs=sp.TList(sp.TRecord(amount=sp.TNat, to_=sp.TAddress, token_id=sp.TNat).layout(("to_", ("token_id", "amount")))))), 
            tokenAddress,
            entry_point='transfer').open_some()

        sp.transfer(arg, sp.mutez(0), transferHandle)

    def transferFA12(self, sender,receiver,amount,tokenAddress): 
        TransferParam = sp.record(
            from_ = sender, 
            to_ = receiver, 
            value = amount
        )
        transferHandle = sp.contract(
            sp.TRecord(from_ = sp.TAddress, to_ = sp.TAddress, value = sp.TNat).layout(("from_ as from", ("to_ as to", "value"))),
            tokenAddress,
            "transfer"
            ).open_some()
        sp.transfer(TransferParam, sp.mutez(0), transferHandle)

    def transferTokenGeneric(self, sender, receiver, amount, tokenAddress,id, tokenType): 
        sp.if tokenType == sp.bounded(FA_2_TOKEN_TYPE): 
            self.transferFA2(sender, receiver, amount , tokenAddress, id )
        sp.else: 
            self.transferFA12(sender, receiver, amount, tokenAddress)


class MarketPlace(sp.Contract, Governance, TransferTokens):
    def __init__(self, administrator):
        self.error = Errors()
        self.init(administrator = administrator,
        markets = sp.big_map(l = {}, tkey = sp.TAddress,
                                tvalue = sp.TRecord(tokenType = TTokenType, sales = sp.TSet(sp.TNat))),
        saleCounter = sp.nat(0),
        sales = sp.big_map(l = {}, tkey = sp.TNat,
                    tvalue = sp.TRecord(tokenAddress = sp.TAddress,
                        tokenId = sp.TNat, 
                        amount = sp.TNat,
                        price = sp.TMutez,
                        seller = sp.TAddress)))
    

    @sp.entry_point
    def registerMarket(self, params):
        sp.set_type(params, sp.TRecord(tokenAddress = sp.TAddress, tokenType = TTokenType))
        self.verifyAdministrator(sp.sender)
        self.verifyMarketNotExists(params.tokenAddress)
        self.data.markets[params.tokenAddress] = sp.record(tokenType = params.tokenType, sales = sp.set([]))


    @sp.entry_point
    def removeMarket(self, tokenAddress):
        sp.set_type(tokenAddress, sp.TAddress)
        self.verifyAdministrator(sp.sender)
        
        sp.for saleId in self.data.markets[tokenAddress].sales.elements():
            self.transferBackTokens(saleId)
            del self.data.sales[saleId]

        del self.data.markets[tokenAddress]


    @sp.entry_point
    def buyAsset(self, saleId):
        sp.set_type(saleId, sp.TNat)
        self.verifySaleExists(saleId)
        sp.verify(sp.amount == self.data.sales[saleId].price, self.error.priceMismatch())

        self.transferTokens(sp.self_address, sp.sender, self.data.sales[saleId].amount, self.data.sales[saleId].tokenAddress, self.data.sales[saleId].tokenId)
        sp.send(self.data.sales[saleId].seller, self.data.sales[saleId].price)

        self.removeSale(saleId)


    @sp.entry_point
    def sellAsset(self, params):
        sp.set_type(params, sp.TRecord(tokenAddress = sp.TAddress, tokenId = sp.TNat, amount = sp.TNat, price = sp.TMutez))
        self.transferTokens(sp.sender, sp.self_address, params.amount, params.tokenAddress, params.tokenId)
        saleId = self.makeSaleId()
        self.data.sales[saleId] = sp.record(tokenAddress =  params.tokenAddress,
                        tokenId = params.tokenId, 
                        amount = params.amount,
                        price = params.price,
                        seller = sp.sender)

        self.data.markets[params.tokenAddress].sales.add(saleId)


    @sp.entry_point
    def cancelSale(self, saleId):
        sp.set_type(saleId, sp.TNat)
        self.verifySaleExists(saleId)
        self.verifyAdminOrSeller(sp.sender, saleId)
        self.transferBackTokens(saleId)
        self.removeSale(saleId)
       

    def verifySaleExists(self, saleId):
        sp.verify(self.data.sales.contains(saleId), self.error.nonExistentSale())


    def verifyMarketNotExists(self, tokenAddress):
        sp.verify(~ self.isMarketExistent(tokenAddress), self.error.alredyRegisteredMarket())


    def verifyMarketExists(self, tokenAddress):
        sp.verify(self.isMarketExistent(tokenAddress), self.error.nonExistentMarket())


    def verifyAdminOrSeller(self, sender, saleId):
        sp.verify(self.isAdministrator(sp.sender) | (sender == self.data.sales[saleId].seller),
         self.error.notAdminOrSeller())


    def transferBackTokens(self, saleId):
        self.transferTokens(sp.self_address,
            self.data.sales[saleId].seller,
            self.data.sales[saleId].amount,
            self.data.sales[saleId].tokenAddress,
            self.data.sales[saleId].tokenId)


    def transferTokens(self, sender, receiver, amount, tokenAddress,id):
        self.transferTokenGeneric(sender, receiver, amount, tokenAddress,id, self.getTokenType(tokenAddress))
    

    def isMarketExistent(self, tokenAddress):
        return self.data.markets.contains(tokenAddress)


    def getTokenType(self, tokenAddress):
        return self.data.markets[tokenAddress].tokenType


    def removeSale(self, saleId):
        self.data.markets[self.data.sales[saleId].tokenAddress].sales.remove(saleId)
        del self.data.sales[saleId]


    def makeSaleId(self):
        self.data.saleCounter += 1
        return self.data.saleCounter

#Tests
@sp.add_test(name = "MarketPlace test")
def test():
        scenario = sp.test_scenario()
        scenario.h1("FA1.2 template - Fungible assets")

        scenario.table_of_contents()


        # sp.test_account generates ED25519 key-pairs deterministically:
        admin = sp.test_account("Administrator")
        alice = sp.test_account("Alice")
        bob   = sp.test_account("Bob")

        # display the accounts:
        scenario.h1("Accounts")
        scenario.show([admin, alice, bob])


        scenario.h1("Contracts initialization")
        scenario.h2("MarketPlace")
        marketPlace = MarketPlace(administrator = admin.address)
        scenario += marketPlace


        scenario.h2("FA1.2 token - fungible silver ounces")
        token_metadata = {
            "decimals"    : "0",
            "name"        : "ounces of silver",   
            "symbol"      : "Silver",              # Silver ounce
            "icon"        : 'https://smartpy.io/static/img/logo-only.svg'
        }
        contract_metadata = {
            "" : "ipfs://QmaiAUj1FFNGYTu8rLBjc3eeN9cSKwaF8EGMBNDmhzPNFd",
        }
        fa12 = FA12.FA12(
            admin.address,
            config              = FA12.FA12_config(support_upgradable_metadata = True),
            token_metadata      = token_metadata,
            contract_metadata   = contract_metadata
        )
        scenario += fa12

        scenario.h3("Initial Minting for Alice")
        fa12.mint(address = alice.address, value = 50).run(sender = admin)
        scenario.h3("Approve interaction with Alice`s balance for marketplace")
        fa12.approve(spender = marketPlace.address, value = 50).run(sender = alice)

        scenario.h2("FA2 NFT token - Gallery's art collection of masterpieces")
        config = FA2.FA2_config(non_fungible = True)
        fa2NFT = FA2.FA2(config = config,
            metadata = sp.utils.metadata_of_url("https://example.com"),
            admin = admin.address)
        scenario += fa2NFT
        scenario.h3("Initial Minting")
        scenario.p("The administrator mints 1 token-0's and token-1.")
        tokenMetadata = FA2.FA2.make_metadata(
            name = "Mona Lisa - Leonardo da Vinci",
            decimals = 0,
            symbol= "LDVMona" )
        monaLisaTokenId = 0
        fa2NFT.mint(address = alice.address,
                            amount = 1,
                            metadata = tokenMetadata,
                            token_id = 0).run(sender = admin)

        tokenMetadata = FA2.FA2.make_metadata(
            name = "Guernica - Pablo Picasso",
            decimals = 0,
            symbol= "PPGuernica" )
        guernicaTokenId = 1
        fa2NFT.mint(address = bob.address,
                            amount = 1,
                            metadata = tokenMetadata,
                            token_id = 1).run(sender = admin)

        scenario.h3("Alice gives an operator for marketPlace")
        fa2NFT.update_operators([
            sp.variant("add_operator", fa2NFT.operator_param.make(
                owner = alice.address,
                operator = marketPlace.address,
                token_id = 0))
        ]).run(sender = alice)


        scenario.h2("FA2 multiasset fungible token - STAXE ICO platform")
        config = FA2.FA2_config()
        fa2FungibleMultiAsset = FA2.FA2(config = config,
            metadata = sp.utils.metadata_of_url("https://staxe.io/creatives-en"),
            admin = admin.address)
        scenario += fa2FungibleMultiAsset
        scenario.h3("Initial minting")
        scenario.p("The administrator mints invested tokens")
        tokenMetadata = FA2.FA2.make_metadata(
            name = "Wake N’Wave Festival",
            decimals = 0,
            symbol= "MonarEP" )
        fa2FungibleMultiAsset.mint(address = alice.address,
                            amount = 100,
                            metadata = tokenMetadata,
                            token_id = 0).run(sender = admin)
        monarEPTokenId = 0

        tokenMetadata = FA2.FA2.make_metadata(
            name = "Luna Llena - Plaza de Toros Las Ventas Madrid concert",
            decimals = 0,
            symbol= "LunaLlena" )
        fa2FungibleMultiAsset.mint(address = bob.address,
                            amount = 40,
                            metadata = tokenMetadata,
                            token_id = 1).run(sender = admin)

        scenario.p("Alice adds operator for marketPlace")
        fa2FungibleMultiAsset.update_operators([
            sp.variant("add_operator", fa2FungibleMultiAsset.operator_param.make(
                owner = alice.address,
                operator = marketPlace.address,
                token_id = monarEPTokenId))
        ]).run(sender = alice)


        scenario.h1("Marketplace")
        scenario.h2("Interaction with FA1.2 token (silver ounces)")

        scenario.h3("Register")
        scenario.h4("[Error] Common user tries to register market")
        params = sp.record(tokenAddress = fa12.address, tokenType = sp.bounded(FA_1_2_TOKEN_TYPE))
        marketPlace.registerMarket(params).run(sender = alice, valid = False)
        scenario.h4("Register FA1.2 token")
        marketPlace.registerMarket(params).run(sender = admin)
        scenario.h4("[Error] Attempt to register already existed market")
        marketPlace.registerMarket(params).run(sender = admin, valid = False)

        scenario.h3("SellAsset")
        scenario.h4("Alice sells 10 silver ounces for 20 000 mutez")
        params = sp.record(tokenAddress = fa12.address, tokenId = 0, amount = sp.nat(10), price = sp.mutez(20000))
        marketPlace.sellAsset(params).run(sender = alice) 
        scenario.verify(fa12.data.balances[alice.address].balance == sp.nat(40))
        lastSaleId = getLastSaleId(marketPlace)

        scenario.h4("Attemp to transer not approved ounces")
        scenario.p("prohibit spending")
        fa12.approve(spender = marketPlace.address, value = 0).run(sender = alice) 
        scenario.p("transfer not allowed")
        marketPlace.sellAsset(params).run(sender = alice, valid = False)
        scenario.p("Alice approves marketPlace`s transfers again")
        fa12.approve(spender = marketPlace.address, value = 50).run(sender = alice)

        scenario.h3("CancelSale")
        scenario.h4("Alice cancels previous sale")
        marketPlace.cancelSale(lastSaleId).run(sender = alice)
        scenario.h4("[Error] Cancel non existent sale")
        marketPlace.cancelSale(sp.nat(0)).run(sender = alice, valid = False)

        scenario.h3("BuyAsset")
        scenario.h4("Alice sells 5 silver ounces for 1 000 mutez")
        params = sp.record(tokenAddress = fa12.address, tokenId = 0, amount = sp.nat(5), price = sp.mutez(1000))
        marketPlace.sellAsset(params).run(sender = alice)
        lastSaleId = getLastSaleId(marketPlace)
        scenario.h4("[Error] Bob tries to buy 5 silver ounces for 1 mutez")
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(1), valid = False)
        scenario.h4("Bob buys 5 silver ounces for 1 000 mutez")
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(1000))
        scenario.h4("[Error] Buy non existent asset")
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(1000), valid = False)
        scenario.h4("[Error] Price mismatch")
        params = sp.record(tokenAddress = fa12.address, tokenId = 0, amount = sp.nat(5), price = sp.mutez(500))
        marketPlace.sellAsset(params).run(sender = alice)
        lastSaleId = getLastSaleId(marketPlace)
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(1000), valid = False)
        marketPlace.cancelSale(lastSaleId).run(sender = alice)

        scenario.h3("RemoveMarket")
        scenario.h4("Alice creates 3 different sales")
        params = sp.record(tokenAddress = fa12.address, tokenId = 0, amount = sp.nat(1), price = sp.mutez(40))
        marketPlace.sellAsset(params).run(sender = alice)
        marketPlace.sellAsset(params).run(sender = alice)
        marketPlace.sellAsset(params).run(sender = alice)
        scenario.h4("[Error] common user tries to remove market")
        marketPlace.removeMarket(fa12.address).run(sender = alice, valid = False)
        scenario.h4("Admin removes market")
        scenario.verify(fa12.data.balances[marketPlace.address].balance != sp.nat(0))
        marketPlace.removeMarket(fa12.address).run(sender = admin)
        scenario.verify(fa12.data.balances[marketPlace.address].balance == sp.nat(0))


        scenario.h2("Interaction with FA2 NFT token - Gallery's art collection of masterpieces")
        scenario.h3("Register token")
        params = sp.record(tokenAddress = fa2NFT.address, tokenType = sp.bounded(FA_2_TOKEN_TYPE))
        marketPlace.registerMarket(params).run(sender = admin)

        scenario.h3("SellAsset")
        scenario.h4("[Error] Bob tries to sell 'Guernica' token without operator")
        params = sp.record(tokenAddress = fa2NFT.address, tokenId = guernicaTokenId, amount = sp.nat(1), price = sp.mutez(1))
        marketPlace.sellAsset(params).run(sender = bob, valid = False) 

        scenario.h4("Alice sells 'Mona Lisa' token")
        params = sp.record(tokenAddress = fa2NFT.address, tokenId = monaLisaTokenId, amount = sp.nat(1), price = sp.mutez(24 * (10 ** 6)))
        marketPlace.sellAsset(params).run(sender = alice) 
        lastSaleId = getLastSaleId(marketPlace)

        scenario.h3("BuyAsset")
        scenario.h4("Bob buys 'Mona Lisa' token")
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(24 * (10 ** 6)))


        scenario.h2("Interaction with FA2 multiasset fungible token - STAXE ICO platform")
        scenario.h3("Register token")
        params = sp.record(tokenAddress = fa2FungibleMultiAsset.address, tokenType = sp.bounded(FA_2_TOKEN_TYPE))
        marketPlace.registerMarket(params).run(sender = admin)

        scenario.h3("SellAsset")
        scenario.h4("Alice sells 'Monar EP' token")
        params = sp.record(tokenAddress = fa2FungibleMultiAsset.address, tokenId = monarEPTokenId, amount = sp.nat(30), price = sp.mutez(33400))
        marketPlace.sellAsset(params).run(sender = alice) 
        lastSaleId = getLastSaleId(marketPlace)

        scenario.h3("BuyAsset")
        scenario.h4("Bob buys 'Monar EP' token")
        marketPlace.buyAsset(lastSaleId).run(sender = bob, amount = sp.mutez(33400))

def getLastSaleId(marketPlace):
    return marketPlace.data.saleCounter


sp.add_compilation_target("MarketPlace", MarketPlace(administrator = sp.address("tz1M9CMEtsXm3QxA7FmMU2Qh7xzsuGXVbcDr")))

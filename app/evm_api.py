import time
from enum import Enum
from http import HTTPMethod, HTTPStatus
from typing import Any, Dict, List, Optional

import requests
from flask import current_app


class EvmApiFailureNoResponse(Exception):
    pass


class EvmApiFailureBadResponse(Exception):
    pass


class EvmApiRateLimitReached(Exception):
    pass


class EvmAccountAction(Enum):
    TX_LIST = "txlist"
    TX_LIST_INTERNAL = "txlistinternal"
    TOKEN_TX = "tokentx"
    TOKEN_NFT_TX = "tokennfttx"
    TOKEN_1155_TX = "token1155tx"


class EvmApi:
    MODULE_ACCOUNT = "account"
    MODULE_CONTRACT = "contract"
    ACTION_GET_CONTRACT_CREATION = "getcontractcreation"
    SORT_ASCENDING = "asc"
    STATUS_NOT_OK = "0"

    def __init__(
        self, rate_limit=5, timeout=30, retries=3, backoff_factor=0.5, tx_per_page=10000
    ) -> None:
        self.session = requests.Session()
        self.last_request_time = float(0)

        self.rate_limit = rate_limit
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.tx_per_page = tx_per_page
        self.retry_after = int(180)

    def _request_with_retries(self, url: str, params: Dict[str, str]) -> List[Any]:
        for attempt in range(self.retries):
            self._rate_limit()
            try:
                request = requests.Request(HTTPMethod.GET, url, params=params)
                requestp = request.prepare()

                current_app.logger.info(
                    f"{id(self)} Request "
                    f"{f'(attempt={attempt+1} of {self.retries}): ' if attempt > 0 else ''}"
                    f"url={requestp.url} timeout={self.timeout}"
                )
                response = self.session.send(requestp, timeout=self.timeout)

                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    current_app.logger.error(
                        f"{id(self)} Bad Response (attempt={attempt+1} of {self.retries}): "
                        f"{requestp.url} status_code={response.status_code} "
                        f"content={response.content.decode()}"
                    )
                    if "retry-after" in response.headers:
                        self.retry_after = int(response.headers["retry-after"])

                    if self._retry(attempt, self.retry_after):
                        continue
                    raise EvmApiFailureBadResponse

                json = response.json()

                if json.get("status") and json["status"] == self.STATUS_NOT_OK:
                    if json.get("result") and "rate limit reached" in json["result"]:
                        raise EvmApiRateLimitReached(
                            f"status_code={response.status_code} "
                            f"content={response.content.decode()}"
                        )

                    if json.get("message") and json["message"] in (
                        "No transactions found",
                        "No internal transactions found",
                        "No token transfers found",
                        "No data found",
                    ):
                        return []

                    current_app.logger.error(
                        f"{id(self)} Bad Response: {requestp.url} "
                        f"status_code={response.status_code} content={response.content.decode()}"
                    )
                    raise EvmApiFailureBadResponse

                if "result" in json and isinstance(json["result"], list):
                    return json["result"]

                current_app.logger.error(
                    f"{id(self)} Bad Response: {requestp.url} "
                    f"status_code={response.status_code} content={response.content.decode()}"
                )
                raise EvmApiFailureBadResponse
            except (requests.exceptions.JSONDecodeError, EvmApiRateLimitReached) as e:
                current_app.logger.error(
                    f"{id(self)} Bad Response (attempt={attempt+1} of {self.retries}): "
                    f"{requestp.url} {e}"
                )
                if not self._retry(attempt):
                    raise EvmApiFailureBadResponse from e
            except (
                requests.exceptions.ConnectionError,
                requests.RequestException,
                requests.exceptions.Timeout,
            ) as e:
                current_app.logger.error(
                    f"{id(self)} No Response (attempt={attempt+1} of {self.retries}): "
                    f"{requestp.url} {e}"
                )
                if not self._retry(attempt):
                    raise EvmApiFailureNoResponse from e

        raise EvmApiFailureNoResponse

    def _rate_limit(self) -> None:
        elapsed_time = time.time() - self.last_request_time
        wait_time = (1 / self.rate_limit) - elapsed_time

        if wait_time > 0:
            current_app.logger.debug(f"{id(self)} Rate-limit, wait: {wait_time:.2f} seconds")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def _retry(self, attempt: int, retry_after: Optional[int] = None) -> bool:
        if attempt < self.retries - 1:
            if retry_after:
                wait_time = retry_after
            else:
                wait_time = self.backoff_factor * (2**attempt)

            current_app.logger.debug(f"{id(self)} Back-off, wait: {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return True
        return False

    def presence_query(self, url: str, params: Dict[str, str], address: str) -> List[Any]:
        params["module"] = EvmApi.MODULE_ACCOUNT
        params["action"] = EvmAccountAction.TX_LIST.value
        params["address"] = address
        params["startblock"] = str(0)
        params["sort"] = EvmApi.SORT_ASCENDING
        params["offset"] = str(100)

        result = self._request_with_retries(url, params)
        return result

    def account_query(
        self, url: str, params: Dict[str, str], action: EvmAccountAction, address: str
    ) -> List[Any]:
        params["module"] = EvmApi.MODULE_ACCOUNT
        params["action"] = action.value
        params["address"] = address
        params["startblock"] = str(0)
        params["sort"] = EvmApi.SORT_ASCENDING
        params["offset"] = str(self.tx_per_page)

        all_tx = []

        while True:
            result = self._request_with_retries(url, params)

            if len(result) < self.tx_per_page:
                all_tx += result
                break

            last_block = result[-1]["blockNumber"]
            if last_block != params["startblock"]:
                # Don't store last block as it maybe incomplete due to pagination
                all_tx += [tx for tx in result if tx["blockNumber"] != last_block]
            else:
                # Store the last block and finish, unlightly tx in the same block will be paginated
                all_tx += [tx for tx in result if tx["blockNumber"] == last_block]
                break

            params["startblock"] = last_block

        return all_tx

    def contract_query(self, url: str, params: Dict[str, str], addresses: List[str]) -> List[Any]:
        params["module"] = EvmApi.MODULE_CONTRACT
        params["action"] = EvmApi.ACTION_GET_CONTRACT_CREATION
        params["contractaddresses"] = ",".join(addresses)

        result = self._request_with_retries(url, params)
        return result


class EtherscanV1Api:
    def __init__(self, api_url: str, api_key: str) -> None:
        self.api_instance = EvmApi()
        self.api_url = api_url
        self.params = {"apikey": current_app.config.get(api_key, "")}

    def presence_query(self, address: str) -> List[Any]:
        return self.api_instance.presence_query(self.api_url, self.params, address)

    def account_query(self, action: EvmAccountAction, address: str) -> List[Any]:
        return self.api_instance.account_query(self.api_url, self.params, action, address)

    def contract_query(self, addresses: List[str]) -> List[Any]:
        return self.api_instance.contract_query(self.api_url, self.params, addresses)


class EtherscanV2Api:
    api_instance = EvmApi(tx_per_page=1000)  # Multi-chain API, use singleton to control throughput

    def __init__(self, evm_chain_id: int) -> None:
        self.api_url = "https://api.etherscan.io/v2/api"
        self.params = {
            "chainid": str(evm_chain_id),
            "apikey": current_app.config["ETHERSCAN_API_KEY"],
        }

    def presence_query(self, address: str) -> List[Any]:
        return EtherscanV2Api.api_instance.presence_query(self.api_url, self.params, address)

    def account_query(self, action: EvmAccountAction, address: str) -> List[Any]:
        return EtherscanV2Api.api_instance.account_query(self.api_url, self.params, action, address)

    def contract_query(self, addresses: List[str]) -> List[Any]:
        return EtherscanV2Api.api_instance.contract_query(self.api_url, self.params, addresses)


class RoutescanV2Api:
    api_instance = EvmApi(rate_limit=2)  # Multi-chain API, use singleton to control throughput

    def __init__(self, evm_chain_id: int) -> None:
        self.api_url = (
            f"https://api.routescan.io/v2/network/mainnet/evm/{evm_chain_id}/etherscan/api"
        )

    def presence_query(self, address: str) -> List[Any]:
        return RoutescanV2Api.api_instance.presence_query(self.api_url, {}, address)

    def account_query(self, action: EvmAccountAction, address: str) -> List[Any]:
        return RoutescanV2Api.api_instance.account_query(self.api_url, {}, action, address)

    def contract_query(self, addresses: List[str]) -> List[Any]:
        return RoutescanV2Api.api_instance.contract_query(self.api_url, {}, addresses)


class BlockscoutApi:
    def __init__(self, api_url: str) -> None:
        self.api_instance = EvmApi(rate_limit=10)
        self.api_url = api_url

    def presence_query(self, address: str) -> List[Any]:
        return self.api_instance.presence_query(self.api_url, {}, address)

    def account_query(self, action: EvmAccountAction, address: str) -> List[Any]:
        return self.api_instance.account_query(self.api_url, {}, action, address)

    def contract_query(self, addresses: List[str]) -> List[Any]:
        return self.api_instance.contract_query(self.api_url, {}, addresses)

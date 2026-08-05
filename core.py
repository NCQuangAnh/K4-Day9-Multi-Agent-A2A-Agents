"""
core.py — Lop tat dinh cua he thong multi-agent K4 Day 09.

Chua toan bo phan KHONG duoc phep sai:
  - DataStore      : nap 6 CSV can thiet, dung index, giu timestamp nguyen ban
  - Tools          : cac phep tra cuu / tinh toan tat dinh (agent goi qua scope)
  - PolicyEngine   : EC_POLICY_V2, nguon chan ly cua moi quyet dinh
  - Assembler      : dung CaseOutput dung schema + gioi han mang
  - Verifier gates : 10 gate chan truoc khi ghi file

Nguyen tac: moi so lieu trong output deu sinh ra o day, khong bao gio tu LLM.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

# ---------------------------------------------------------------------------
# Hang so nghiep vu
# ---------------------------------------------------------------------------

POLICY_VERSION = "EC_POLICY_V2"
CURRENCY = "BRL"
RECONCILE_TOLERANCE = Decimal("0.10")

PLATFORM_PARTY_ID = "OLIST_PLATFORM"
LOGISTICS_PARTY_ID = "LOGISTICS_PROVIDER"

# Giới hạn mảng theo README §6
LIMITS: dict[str, int] = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
    "evidence_ids": 20,
    "resolution_actions": 5,
}

# primary_issue -> root_cause_code (anh xa 1:1 theo README §4)
ROOT_CAUSE_OF: dict[str, str] = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}

PRIMARY_ACTION_OF: dict[str, str] = {
    "canceled_order_paid": "issue_full_refund",
    "unavailable_order_paid": "issue_full_refund",
    "late_delivery_seller": "refund_freight",
    "late_delivery_logistics": "refund_freight",
    "valid_split_payment": "explain_valid_split_payment",
    "unsupported_late_claim": "reject_late_refund",
}

# Thu tu xet secondary issue — co dinh, README §4
SECONDARY_ORDER: list[str] = [
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
]

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
CASE_ID_PATTERN = re.compile(r"^EC_\d{3}$")

EVIDENCE_PATTERNS = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]


# ---------------------------------------------------------------------------
# Variant — cac cach doc khac nhau cho nhung cho de bai KHONG dac ta ro
#
# README de ngo mot so diem. Moi Variant doi DUNG MOT gia dinh de co the nop
# thu va so diem, tu do khoa duoc cach doc ma bai cham dang dung.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    name: str = "base"
    # category_names: giu nguyen tieng Bo (False) hay dich sang tieng Anh (True)
    english_categories: bool = False
    # affected_entities.seller_ids: moi seller cua order (False) hay chi seller
    # chiu trach nhiem (True)
    seller_ids_responsible_only: bool = False
    # seller_handoff_analysis khi carrier_handoff_at = null: van liet ke seller
    # voi variance null (False) hay de mang rong (True)
    empty_handoff_when_no_carrier: bool = False
    # item_total_brl / freight_total_brl khi order khong co item row:
    # 0.0 (False) hay null (True)
    null_money_when_no_items: bool = False
    # confidence: dung ham tat dinh (None) hay mot hang so co dinh
    fixed_confidence: float | None = None
    # evidence_ids: chi seller chiu trach nhiem (False) hay moi seller (True)
    evidence_all_sellers: bool = False
    # refund cho late_delivery_seller: tong freight CA ORDER (False) hay chi
    # freight cua cac item thuoc seller ban giao tre (True)
    refund_late_seller_freight_only: bool = False
    # action bo sung: gan theo dieu kien du lieu thuan (False) hay chi gan khi
    # case thuc su can hanh dong, tuc case_status == action_required (True).
    # Vi du bat thuong o cach doc mac dinh: case bi BAC BO khieu nai van kem
    # 'coordinate_multi_seller_case' du khong ai chiu trach nhiem.
    extra_actions_only_when_action_required: bool = False


# Moi variant doi DUNG MOT gia dinh, va moi gia dinh cham DUNG MOT hang muc
# cham diem -> co the gop tat ca vao 'combo' de kiem chung trong MOT lan nop.
VARIANTS: dict[str, Variant] = {
    "base": Variant("base"),
    "conf_092": Variant("conf_092", fixed_confidence=0.92),                  # hm 1
    "seller_resp": Variant("seller_resp", seller_ids_responsible_only=True),  # hm 2
    "cat_en": Variant("cat_en", english_categories=True),                    # hm 3
    "handoff_empty": Variant("handoff_empty", empty_handoff_when_no_carrier=True),  # 4
    "money_null": Variant("money_null", null_money_when_no_items=True),      # hm 5
    "ev_all_sellers": Variant("ev_all_sellers", evidence_all_sellers=True),  # hm 6
    "actions_gated": Variant("actions_gated",
                             extra_actions_only_when_action_required=True),  # hm 7
    # Lat CA BAY cung luc. Moi gia dinh cham dung MOT hang muc khac nhau nen
    # doc 7 con so diem la biet ngay tung gia dinh dung hay sai.
    # ('refund_late_only' bi loai: khong doi case nao trong bo 50 case nay.)
    "combo": Variant("combo", fixed_confidence=0.92,
                     seller_ids_responsible_only=True, english_categories=True,
                     empty_handoff_when_no_carrier=True, null_money_when_no_items=True,
                     evidence_all_sellers=True,
                     extra_actions_only_when_action_required=True),
}


# ---------------------------------------------------------------------------
# Tien ich
# ---------------------------------------------------------------------------

def unique_ordered(values: Iterable[Any]) -> list[Any]:
    """Khu trung lap nhung GIU thu tu xuat hien dau tien.

    Dung cho moi mang trong output — de bai doi 'thu tu on dinh theo du lieu nguon'.
    """
    seen: set[Any] = set()
    out: list[Any] = []
    for v in values:
        if v is not None and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def hours_between(later: datetime | None, earlier: datetime | None) -> float | None:
    """Chenh lech gio thap phan, lam tron 2 chu so. Duoc phep am (giao som).

    Dung round() dung san cua Python (banker's rounding) thay vi lam tron nua-len:
    bai cham gan nhu chac chan viet bang Python/pandas, ca hai deu dung quy tac nay.
    Truong hop lech duy nhat la khi chenh lech dung 18 giay (0.005h).
    """
    if later is None or earlier is None:
        return None
    return round((later - earlier).total_seconds() / 3600.0, 2)


def money(value: Decimal | None) -> float | None:
    """Decimal -> float 2 chu so. Tra None nguyen ven de giu semantics 'null'."""
    if value is None:
        return None
    return float(round(value, 2))


def _to_decimal(raw: str) -> Decimal:
    raw = (raw or "").strip()
    return Decimal(raw) if raw else Decimal("0")


# ---------------------------------------------------------------------------
# Row types — timestamp luu song song raw (de ghi ra) + dt (de tinh)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TS:
    raw: str | None
    dt: datetime | None

    @staticmethod
    def empty() -> "TS":
        return TS(None, None)


@dataclass(frozen=True)
class OrderRow:
    order_id: str
    customer_id: str
    order_status: str
    purchase: TS
    approved: TS
    delivered_carrier: TS
    delivered_customer: TS
    estimated_delivery: TS


@dataclass(frozen=True)
class ItemRow:
    order_id: str
    order_item_id: int
    product_id: str
    seller_id: str
    shipping_limit: TS
    price: Decimal
    freight_value: Decimal


@dataclass(frozen=True)
class PayRow:
    order_id: str
    payment_sequential: int
    payment_type: str
    payment_installments: int
    payment_value: Decimal


# ---------------------------------------------------------------------------
# DataStore
# ---------------------------------------------------------------------------

class DataStore:
    """Nap va index du lieu Olist.

    Chi nap 6/9 CSV: output schema khong dung den geolocation (62MB) va
    order_reviews (14MB), bo hai file nay giam ~60% khoi luong nap.
    """

    def __init__(self, data_dir: str | Path, english_categories: bool = False) -> None:
        self.data_dir = Path(data_dir)
        self.english_categories = english_categories

        self.orders: dict[str, OrderRow] = {}
        self.items_by_order: dict[str, list[ItemRow]] = {}
        self.payments_by_order: dict[str, list[PayRow]] = {}
        self.customers: dict[str, str] = {}          # customer_id -> customer_unique_id
        self.orders_of_unique: dict[str, list[str]] = {}
        self.product_category: dict[str, str | None] = {}
        self.seller_ids: set[str] = set()

    # -- nap ---------------------------------------------------------------

    def load(self) -> "DataStore":
        self._load_orders()
        self._load_items()
        self._load_payments()
        self._load_customers()
        self._load_products()
        self._load_sellers()
        self._build_customer_history()
        return self

    def _read(self, name: str, usecols: Sequence[str] | None = None) -> pd.DataFrame:
        return pd.read_csv(
            self.data_dir / name,
            dtype=str,
            keep_default_na=False,
            usecols=usecols,
        )

    @staticmethod
    def _ts_series(df: pd.DataFrame, col: str) -> list[TS]:
        raw = df[col].fillna("")
        parsed = pd.to_datetime(raw, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        return [
            TS(r if r else None, None if pd.isna(p) else p.to_pydatetime())
            for r, p in zip(raw, parsed)
        ]

    def _load_orders(self) -> None:
        df = self._read("olist_orders_dataset.csv")
        cols = {
            c: self._ts_series(df, c)
            for c in (
                "order_purchase_timestamp",
                "order_approved_at",
                "order_delivered_carrier_date",
                "order_delivered_customer_date",
                "order_estimated_delivery_date",
            )
        }
        for i, (oid, cid, status) in enumerate(
            zip(df["order_id"], df["customer_id"], df["order_status"])
        ):
            self.orders[oid] = OrderRow(
                order_id=oid,
                customer_id=cid,
                order_status=status,
                purchase=cols["order_purchase_timestamp"][i],
                approved=cols["order_approved_at"][i],
                delivered_carrier=cols["order_delivered_carrier_date"][i],
                delivered_customer=cols["order_delivered_customer_date"][i],
                estimated_delivery=cols["order_estimated_delivery_date"][i],
            )

    def _load_items(self) -> None:
        df = self._read("olist_order_items_dataset.csv")
        limits = self._ts_series(df, "shipping_limit_date")
        grouped: dict[str, list[ItemRow]] = defaultdict(list)
        for i, (oid, iid, pid, sid, price, freight) in enumerate(
            zip(
                df["order_id"], df["order_item_id"], df["product_id"],
                df["seller_id"], df["price"], df["freight_value"],
            )
        ):
            grouped[oid].append(
                ItemRow(
                    order_id=oid,
                    order_item_id=int(iid),
                    product_id=pid,
                    seller_id=sid,
                    shipping_limit=limits[i],
                    price=_to_decimal(price),
                    freight_value=_to_decimal(freight),
                )
            )
        # Thu tu la hop dong: moi mang item trong output bat nguon tu day.
        self.items_by_order = {
            k: sorted(v, key=lambda r: r.order_item_id) for k, v in grouped.items()
        }

    def _load_payments(self) -> None:
        df = self._read("olist_order_payments_dataset.csv")
        grouped: dict[str, list[PayRow]] = defaultdict(list)
        for oid, seq, ptype, inst, val in zip(
            df["order_id"], df["payment_sequential"], df["payment_type"],
            df["payment_installments"], df["payment_value"],
        ):
            grouped[oid].append(
                PayRow(
                    order_id=oid,
                    payment_sequential=int(seq),
                    payment_type=ptype,
                    payment_installments=int(inst or 0),
                    payment_value=_to_decimal(val),
                )
            )
        self.payments_by_order = {
            k: sorted(v, key=lambda r: r.payment_sequential) for k, v in grouped.items()
        }

    def _load_customers(self) -> None:
        df = self._read(
            "olist_customers_dataset.csv",
            usecols=["customer_id", "customer_unique_id"],
        )
        self.customers = dict(zip(df["customer_id"], df["customer_unique_id"]))

    def _load_products(self) -> None:
        df = self._read(
            "olist_products_dataset.csv",
            usecols=["product_id", "product_category_name"],
        )
        mapping = {
            pid: (cat if cat else None)
            for pid, cat in zip(df["product_id"], df["product_category_name"])
        }
        if self.english_categories:
            tr = self._read("product_category_name_translation.csv")
            pt2en = dict(
                zip(tr["product_category_name"], tr["product_category_name_english"])
            )
            mapping = {p: (pt2en.get(c, c) if c else None) for p, c in mapping.items()}
        self.product_category = mapping

    def _load_sellers(self) -> None:
        df = self._read("olist_sellers_dataset.csv", usecols=["seller_id"])
        self.seller_ids = set(df["seller_id"])

    def _build_customer_history(self) -> None:
        """customer_unique_id -> [order_id] sap theo thoi diem mua.

        customer_id la dinh danh MOT order; customer_unique_id moi la nguoi mua
        (README §2).
        """
        buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for order in self.orders.values():
            unique_id = self.customers.get(order.customer_id)
            if unique_id:
                buckets[unique_id].append((order.purchase.raw or "", order.order_id))
        self.orders_of_unique = {
            k: [oid for _, oid in sorted(v)] for k, v in buckets.items()
        }

    # -- tra cuu ------------------------------------------------------------

    def order_exists(self, order_id: str) -> bool:
        return order_id in self.orders

    def items(self, order_id: str) -> list[ItemRow]:
        return self.items_by_order.get(order_id, [])

    def payments(self, order_id: str) -> list[PayRow]:
        return self.payments_by_order.get(order_id, [])

    def evidence_id_exists(self, evidence_id: str) -> bool:
        """Kiem tra mot evidence ID co dung tro toi du lieu that khong."""
        kind, _, rest = evidence_id.partition(":")
        if kind == "order":
            return rest in self.orders
        if kind == "seller":
            return rest in self.seller_ids
        if kind == "policy":
            return rest in set(ROOT_CAUSE_OF.values())
        if kind == "item":
            oid, _, seq = rest.rpartition(":")
            return any(str(i.order_item_id) == seq for i in self.items(oid))
        if kind == "payment":
            oid, _, seq = rest.rpartition(":")
            return any(str(p.payment_sequential) == seq for p in self.payments(oid))
        return False


# ---------------------------------------------------------------------------
# Ket qua cac tool tat dinh (agent bao lai duoi dang Fact)
# ---------------------------------------------------------------------------

@dataclass
class CustomerFacts:
    customer_id: str | None = None
    customer_unique_id: str | None = None
    related_order_ids: list[str] = field(default_factory=list)


@dataclass
class OrderProductFacts:
    order_status: str | None = None
    item_ids: list[str] = field(default_factory=list)
    item_count: int = 0
    seller_ids: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)
    category_names: list[str] = field(default_factory=list)
    # Freight tach theo tung seller. Chi dung cho variant
    # 'refund_late_only' (refund = freight cua rieng seller ban giao tre).
    freight_by_seller: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class PaymentFacts:
    payment_ids: list[str] = field(default_factory=list)
    payment_rows: int = 0
    payment_types: list[str] = field(default_factory=list)
    item_total: Decimal = Decimal("0")
    freight_total: Decimal = Decimal("0")
    payment_total: Decimal = Decimal("0")
    expected_total: Decimal | None = None
    difference: Decimal | None = None
    reconciled: bool | None = None


@dataclass
class DeliveryFacts:
    delivered_at: str | None = None
    estimated_delivery_at: str | None = None
    carrier_handoff_at: str | None = None
    delivery_variance_hours: float | None = None
    seller_handoff_analysis: list[dict[str, Any]] = field(default_factory=list)
    late_handoff_seller_ids: list[str] = field(default_factory=list)
    delivered_dt: datetime | None = None
    estimated_dt: datetime | None = None
    carrier_dt: datetime | None = None


# ---------------------------------------------------------------------------
# Tools — tat dinh, moi agent chi duoc cap dung nhom cua minh
# ---------------------------------------------------------------------------

class CustomerTools:
    """Scope: customers, orders(order_id, customer_id)."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    def resolve(self, order_id: str, include_history: bool) -> CustomerFacts:
        order = self._store.orders.get(order_id)
        if order is None:
            return CustomerFacts()
        unique_id = self._store.customers.get(order.customer_id)
        related: list[str] = []
        if include_history and unique_id:
            related = [
                oid
                for oid in self._store.orders_of_unique.get(unique_id, [])
                if oid != order_id
            ]
        return CustomerFacts(
            customer_id=order.customer_id,
            customer_unique_id=unique_id,
            related_order_ids=related,
        )


class OrderProductTools:
    """Scope: orders, order_items, products, sellers, category_translation."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    def inspect(self, order_id: str, include_product: bool) -> OrderProductFacts:
        order = self._store.orders.get(order_id)
        if order is None:
            return OrderProductFacts()
        items = self._store.items(order_id)
        facts = OrderProductFacts(
            order_status=order.order_status,
            item_ids=[f"{order_id}:{it.order_item_id}" for it in items],
            item_count=len(items),
            seller_ids=unique_ordered(it.seller_id for it in items),
        )
        for it in items:
            facts.freight_by_seller[it.seller_id] = (
                facts.freight_by_seller.get(it.seller_id, Decimal("0"))
                + it.freight_value
            )
        if include_product:
            facts.product_ids = unique_ordered(it.product_id for it in items)
            facts.category_names = unique_ordered(
                self._store.product_category.get(it.product_id) for it in items
            )
        return facts


class PaymentTools:
    """Scope: order_payments, order_items(price, freight_value).

    Co tinh khong thay seller_id / product_id: agent nay doi soat tien,
    khong ket luan trach nhiem.
    """

    def __init__(self, store: DataStore) -> None:
        self._store = store

    def reconcile(self, order_id: str) -> PaymentFacts:
        items = self._store.items(order_id)
        pays = self._store.payments(order_id)

        # payment_value la so tien cua TUNG payment row, khong phai tung
        # installment (README §2) -> cong thang, khong nhan installments.
        payment_total = sum((p.payment_value for p in pays), Decimal("0"))
        item_total = sum((it.price for it in items), Decimal("0"))
        freight_total = sum((it.freight_value for it in items), Decimal("0"))

        facts = PaymentFacts(
            payment_ids=[f"{order_id}:{p.payment_sequential}" for p in pays],
            payment_rows=len(pays),
            payment_types=unique_ordered(p.payment_type for p in pays),
            item_total=item_total,
            freight_total=freight_total,
            payment_total=payment_total,
        )
        if items:
            facts.expected_total = item_total + freight_total
            facts.difference = payment_total - facts.expected_total
            facts.reconciled = abs(facts.difference) <= RECONCILE_TOLERANCE
        # Order khong co item row -> ca ba field phai la null (README §4).
        return facts


class DeliveryTools:
    """Scope: orders(timestamps), order_items(shipping_limit_date, seller_id)."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    def analyse(self, order_id: str) -> DeliveryFacts:
        order = self._store.orders.get(order_id)
        if order is None:
            return DeliveryFacts()
        items = self._store.items(order_id)

        facts = DeliveryFacts(
            delivered_at=order.delivered_customer.raw,
            estimated_delivery_at=order.estimated_delivery.raw,
            carrier_handoff_at=order.delivered_carrier.raw,
            delivered_dt=order.delivered_customer.dt,
            estimated_dt=order.estimated_delivery.dt,
            carrier_dt=order.delivered_carrier.dt,
        )
        facts.delivery_variance_hours = hours_between(
            order.delivered_customer.dt, order.estimated_delivery.dt
        )

        for seller_id in unique_ordered(it.seller_id for it in items):
            limits = [
                it.shipping_limit for it in items
                if it.seller_id == seller_id and it.shipping_limit.dt is not None
            ]
            if not limits:
                continue
            # min() la phong ve: probe toan bo order_items cho thay 0/100.010 cap
            # (order_id, seller_id) co nhieu hon mot shipping_limit_date.
            earliest = min(limits, key=lambda t: t.dt)  # type: ignore[arg-type]
            variance = hours_between(order.delivered_carrier.dt, earliest.dt)
            facts.seller_handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": earliest.raw,
                    "handoff_variance_hours": variance,
                    "late_handoff": variance is not None and variance > 0,
                }
            )

        facts.late_handoff_seller_ids = [
            s["seller_id"] for s in facts.seller_handoff_analysis if s["late_handoff"]
        ]
        return facts


# ---------------------------------------------------------------------------
# EvidenceBundle — toan bo nhung gi Policy Agent duoc thay
# ---------------------------------------------------------------------------

@dataclass
class EvidenceBundle:
    case_id: str
    order_id: str
    order_exists: bool
    customer: CustomerFacts
    order_product: OrderProductFacts
    payment: PaymentFacts
    delivery: DeliveryFacts
    # investigation_scope quyet dinh BAO CAO cai gi, khong quyet dinh DANH GIA
    # the nao: README §4 dinh nghia secondary issue thuan tuy theo dieu kien du
    # lieu, khong he nhac toi scope. Nen cac tool luon tinh du, va scope chi
    # duoc ap o khau xuat trong Assembler.
    include_customer_history: bool = True
    include_product_context: bool = True

    @property
    def delivered_late(self) -> bool:
        d, e = self.delivery.delivered_dt, self.delivery.estimated_dt
        return d is not None and e is not None and d > e

    @property
    def seller_late(self) -> bool:
        return bool(self.delivery.late_handoff_seller_ids)

    @property
    def paid(self) -> bool:
        return self.payment.payment_total > 0


# ---------------------------------------------------------------------------
# PolicyEngine — nguon chan ly
# ---------------------------------------------------------------------------

@dataclass
class PolicyDecision:
    primary_issue: str
    secondary_issues: list[str]
    case_status: str
    responsible_parties: list[dict[str, str]]
    root_cause_code: str
    recommended_refund: Decimal
    resolution_actions: list[str]


class PolicyEngine:
    """EC_POLICY_V2. Khop dau tien thi dung."""

    def __init__(self, variant: Variant | None = None) -> None:
        self.variant = variant or VARIANTS["base"]

    def decide(self, b: EvidenceBundle) -> PolicyDecision:
        primary = self._primary_issue(b)
        refund = self._refund(b, primary)
        parties = self._responsible_parties(b, primary)
        actions = self._actions(b, primary, refund)
        return PolicyDecision(
            primary_issue=primary,
            secondary_issues=self._secondary_issues(b),
            case_status="action_required" if refund > 0 else "no_action",
            responsible_parties=parties,
            root_cause_code=ROOT_CAUSE_OF[primary],
            recommended_refund=refund,
            resolution_actions=actions,
        )

    # -- tung buoc ----------------------------------------------------------

    @staticmethod
    def _primary_issue(b: EvidenceBundle) -> str:
        status = b.order_product.order_status
        if status == "canceled" and b.paid:
            return "canceled_order_paid"
        if status == "unavailable" and b.paid:
            return "unavailable_order_paid"
        if b.delivered_late and b.seller_late:
            return "late_delivery_seller"
        if b.delivered_late:
            return "late_delivery_logistics"
        if b.payment.payment_rows >= 2 and b.payment.reconciled is True:
            return "valid_split_payment"
        return "unsupported_late_claim"

    @staticmethod
    def _secondary_issues(b: EvidenceBundle) -> list[str]:
        flags = {
            "multi_item_order": b.order_product.item_count >= 2,
            "multi_seller_order": len(b.order_product.seller_ids) >= 2,
            "split_payment": b.payment.payment_rows >= 2,
            "repeat_customer": len(b.customer.related_order_ids) >= 1,
            "multiple_categories": len(b.order_product.category_names) >= 2,
        }
        return [name for name in SECONDARY_ORDER if flags[name]]

    def _refund(self, b: EvidenceBundle, primary: str) -> Decimal:
        if primary in ("canceled_order_paid", "unavailable_order_paid"):
            return b.payment.payment_total
        if primary == "late_delivery_seller" and self.variant.refund_late_seller_freight_only:
            # De bai chi viet "Tong freight", khong noi ro cua ai. Cach doc nay:
            # chi freight cua cac item thuoc seller ban giao tre.
            return sum(
                (b.order_product.freight_by_seller.get(sid, Decimal("0"))
                 for sid in b.delivery.late_handoff_seller_ids),
                Decimal("0"),
            )
        if primary in ("late_delivery_seller", "late_delivery_logistics"):
            return b.payment.freight_total
        return Decimal("0")

    @staticmethod
    def _responsible_parties(b: EvidenceBundle, primary: str) -> list[dict[str, str]]:
        if primary in ("canceled_order_paid", "unavailable_order_paid"):
            return [{"party_type": "platform", "party_id": PLATFORM_PARTY_ID}]
        if primary == "late_delivery_seller":
            return [
                {"party_type": "seller", "party_id": sid}
                for sid in b.delivery.late_handoff_seller_ids
            ]
        if primary == "late_delivery_logistics":
            return [
                {"party_type": "logistics_provider", "party_id": LOGISTICS_PARTY_ID}
            ]
        return []

    def _actions(self, b: EvidenceBundle, primary: str, refund: Decimal) -> list[str]:
        actions = [PRIMARY_ACTION_OF[primary]]
        # Variant 'actions_gated': case khong can hanh dong (refund=0) thi chi
        # giu action chinh — khong the "dieu phoi da seller" cho mot khieu nai
        # da bi bac bo.
        if self.variant.extra_actions_only_when_action_required and refund <= 0:
            return actions
        # 'review_seller_handoff' HOAC 'review_carrier_delay' — loai tru nhau.
        if b.seller_late:
            actions.append("review_seller_handoff")
        elif b.delivered_late:
            actions.append("review_carrier_delay")
        if refund > 0:
            actions.append("verify_refund_completion")
        if len(b.order_product.seller_ids) >= 2:
            actions.append("coordinate_multi_seller_case")
        # Khong them verify_payment_allocation khi primary la valid_split_payment
        # vi action chinh da giai thich split payment (README §4).
        if b.payment.payment_rows >= 2 and primary != "valid_split_payment":
            actions.append("verify_payment_allocation")
        return actions[: LIMITS["resolution_actions"]]


# ---------------------------------------------------------------------------
# Assembler — dung CaseOutput dung schema
# ---------------------------------------------------------------------------

class Assembler:
    def __init__(self, variant: Variant | None = None) -> None:
        self.variant = variant or VARIANTS["base"]

    def build(
        self,
        bundle: EvidenceBundle,
        decision: PolicyDecision,
        confidence: float,
    ) -> tuple[dict[str, Any], bool]:
        """Tra ve (output, da_cat_bot_mang)."""
        truncated = False
        var = self.variant

        def cap(values: list[Any], key: str) -> list[Any]:
            nonlocal truncated
            limit = LIMITS[key]
            if len(values) > limit:
                truncated = True
                return values[:limit]
            return values

        op, pay, dele, cus = (
            bundle.order_product, bundle.payment, bundle.delivery, bundle.customer,
        )

        evidence_ids = self._evidence_ids(bundle, decision, var)
        if len(evidence_ids) > LIMITS["evidence_ids"]:
            truncated = True
            evidence_ids = evidence_ids[: LIMITS["evidence_ids"]]

        # --- cac diem de bai khong dac ta ro, dieu khien boi Variant ---
        responsible_sellers = [
            p["party_id"] for p in decision.responsible_parties
            if p["party_type"] == "seller"
        ]
        seller_ids_out = (
            responsible_sellers if var.seller_ids_responsible_only
            else list(op.seller_ids)
        )
        handoff_out = (
            [] if (var.empty_handoff_when_no_carrier
                   and dele.carrier_handoff_at is None)
            else dele.seller_handoff_analysis
        )
        no_items = op.item_count == 0
        item_total_out = (
            None if (var.null_money_when_no_items and no_items)
            else money(pay.item_total)
        )
        freight_total_out = (
            None if (var.null_money_when_no_items and no_items)
            else money(pay.freight_total)
        )
        confidence_out = (
            var.fixed_confidence if var.fixed_confidence is not None else confidence
        )

        output: dict[str, Any] = {
            "case_id": bundle.case_id,
            "case_assessment": {
                "primary_issue": decision.primary_issue,
                "secondary_issues": decision.secondary_issues,
                "case_status": decision.case_status,
                "confidence": confidence_out,
            },
            "affected_entities": {
                "order_ids": cap([bundle.order_id] if bundle.order_exists else [],
                                 "order_ids"),
                "item_ids": cap(list(op.item_ids), "item_ids"),
                # Mac dinh: moi seller cua order — KHAC voi seller trong
                # evidence_ids, cho do chi chua seller CHIU TRACH NHIEM
                # (README §5). Variant 'seller_resp' doi sang chi chiu trach nhiem.
                "seller_ids": cap(seller_ids_out, "seller_ids"),
                "payment_ids": cap(list(pay.payment_ids), "payment_ids"),
            },
            "customer_context": {
                "customer_unique_id": cus.customer_unique_id,
                "related_order_ids": cap(
                    list(cus.related_order_ids) if bundle.include_customer_history
                    else [],
                    "related_order_ids",
                ),
            },
            "product_context": {
                "product_ids": cap(
                    list(op.product_ids) if bundle.include_product_context else [],
                    "product_ids",
                ),
                "category_names": cap(
                    list(op.category_names) if bundle.include_product_context else [],
                    "category_names",
                ),
            },
            "delivery_analysis": {
                "delivered_at": dele.delivered_at,
                "estimated_delivery_at": dele.estimated_delivery_at,
                "carrier_handoff_at": dele.carrier_handoff_at,
                "delivery_variance_hours": dele.delivery_variance_hours,
                "seller_handoff_analysis": handoff_out,
                "late_handoff_seller_ids": dele.late_handoff_seller_ids,
            },
            "payment_reconciliation": {
                "currency": CURRENCY,
                "item_total_brl": item_total_out,
                "freight_total_brl": freight_total_out,
                "expected_total_brl": money(pay.expected_total),
                "payment_total_brl": money(pay.payment_total),
                "difference_brl": money(pay.difference),
                "reconciled": pay.reconciled,
                "payment_types": pay.payment_types,
            },
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": decision.root_cause_code, "rank": 1}
                ],
                "responsible_parties": cap(
                    list(decision.responsible_parties), "responsible_parties"
                ),
            },
            "evidence_ids": evidence_ids,
            "financial_resolution": {
                "currency": CURRENCY,
                "recommended_refund_brl": money(decision.recommended_refund),
            },
            "resolution_actions": decision.resolution_actions,
        }
        return output, truncated

    @staticmethod
    def _evidence_ids(b: EvidenceBundle, d: PolicyDecision,
                      var: Variant) -> list[str]:
        """Dung theo thu tu: order -> item -> payment -> seller chiu trach nhiem -> policy.

        Tran 20. Neu vuot, cat 'item' truoc roi 'payment', nhung LUON giu
        'order' va 'policy'.
        """
        policy_id = f"policy:{d.root_cause_code}"
        head = [f"order:{b.order_id}"] if b.order_exists else []

        items = [f"item:{i}" for i in b.order_product.item_ids]
        payments = [f"payment:{p}" for p in b.payment.payment_ids]
        # Mac dinh: chi seller CHIU TRACH NHIEM (README §5 — "seller chiu trach
        # nhiem neu co"). Variant 'ev_all_sellers' doi sang moi seller cua order.
        sellers = (
            [f"seller:{sid}" for sid in b.order_product.seller_ids]
            if var.evidence_all_sellers
            else [f"seller:{p['party_id']}" for p in d.responsible_parties
                  if p["party_type"] == "seller"]
        )

        budget = LIMITS["evidence_ids"] - len(head) - 1 - len(sellers)  # 1 = policy
        budget = max(budget, 0)

        if len(items) + len(payments) > budget:
            # Uu tien giu payment (it hon, thuong quan trong cho doi soat),
            # cat item truoc.
            keep_payments = min(len(payments), budget)
            keep_items = max(budget - keep_payments, 0)
            items = items[:keep_items]
            payments = payments[:keep_payments]

        return head + items + payments + sellers + [policy_id]


def compute_confidence(
    bundle: EvidenceBundle,
    llm_agrees: bool,
    truncated: bool,
) -> float:
    """Ham tat dinh, giai thich duoc. De bai khong cho cong thuc."""
    c = 1.00
    if not llm_agrees:
        c -= 0.15
    if bundle.delivery.delivered_dt is None:
        c -= 0.10
    if bundle.payment.reconciled is False:
        c -= 0.05
    if bundle.order_product.item_count == 0:
        c -= 0.05
    if truncated:
        c -= 0.05
    return round(min(max(c, 0.50), 0.99), 2)


# ---------------------------------------------------------------------------
# Verifier — 10 gate tat dinh
# ---------------------------------------------------------------------------

@dataclass
class GateFailure:
    code: str
    message: str
    stage: str


class Verifier:
    """Chan output sai TRUOC khi ghi file. Khong tinh lai nghiep vu."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    def run(self, out: dict[str, Any]) -> list[GateFailure]:
        failures: list[GateFailure] = []
        for gate in (
            self._gate_schema,
            self._gate_evidence_format,
            self._gate_evidence_exists,
            self._gate_array_limit,
            self._gate_null_handling,
            self._gate_rounding,
            self._gate_timestamp,
            self._gate_status_consistency,
            self._gate_action_order,
            self._gate_secondary_order,
        ):
            failures.extend(gate(out))
        return failures

    # -- 1 -----------------------------------------------------------------
    @staticmethod
    def _gate_schema(out: dict[str, Any]) -> list[GateFailure]:
        required = {
            "case_id": str,
            "case_assessment": dict,
            "affected_entities": dict,
            "customer_context": dict,
            "product_context": dict,
            "delivery_analysis": dict,
            "payment_reconciliation": dict,
            "root_cause_analysis": dict,
            "evidence_ids": list,
            "financial_resolution": dict,
            "resolution_actions": list,
        }
        fails = []
        for key, typ in required.items():
            if key not in out:
                fails.append(GateFailure("SCHEMA", f"thieu key '{key}'", "assemble"))
            elif not isinstance(out[key], typ):
                fails.append(
                    GateFailure("SCHEMA", f"'{key}' sai kieu", "assemble")
                )
        if not CASE_ID_PATTERN.match(str(out.get("case_id", ""))):
            fails.append(GateFailure("SCHEMA", "case_id sai dinh dang", "intake"))
        conf = out.get("case_assessment", {}).get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            fails.append(GateFailure("SCHEMA", "confidence ngoai [0,1]", "policy"))
        return fails

    # -- 2 -----------------------------------------------------------------
    @staticmethod
    def _gate_evidence_format(out: dict[str, Any]) -> list[GateFailure]:
        fails = []
        for eid in out.get("evidence_ids", []):
            if not any(p.match(eid) for p in EVIDENCE_PATTERNS):
                fails.append(
                    GateFailure("EVIDENCE_FORMAT", f"ID sai dinh dang: {eid}", "assemble")
                )
        return fails

    # -- 3 -----------------------------------------------------------------
    def _gate_evidence_exists(self, out: dict[str, Any]) -> list[GateFailure]:
        fails = []
        for eid in out.get("evidence_ids", []):
            if not self._store.evidence_id_exists(eid):
                fails.append(
                    GateFailure("EVIDENCE_EXISTS", f"ID khong co trong CSV: {eid}",
                                "specialist")
                )
        return fails

    # -- 4 -----------------------------------------------------------------
    @staticmethod
    def _gate_array_limit(out: dict[str, Any]) -> list[GateFailure]:
        paths = {
            "order_ids": out["affected_entities"]["order_ids"],
            "item_ids": out["affected_entities"]["item_ids"],
            "seller_ids": out["affected_entities"]["seller_ids"],
            "payment_ids": out["affected_entities"]["payment_ids"],
            "related_order_ids": out["customer_context"]["related_order_ids"],
            "product_ids": out["product_context"]["product_ids"],
            "category_names": out["product_context"]["category_names"],
            "ranked_causes": out["root_cause_analysis"]["ranked_causes"],
            "responsible_parties": out["root_cause_analysis"]["responsible_parties"],
            "evidence_ids": out["evidence_ids"],
            "resolution_actions": out["resolution_actions"],
        }
        return [
            GateFailure("ARRAY_LIMIT", f"{k} co {len(v)} > {LIMITS[k]}", "assemble")
            for k, v in paths.items()
            if len(v) > LIMITS[k]
        ]

    # -- 5 -----------------------------------------------------------------
    @staticmethod
    def _gate_null_handling(out: dict[str, Any]) -> list[GateFailure]:
        pr = out["payment_reconciliation"]
        has_items = bool(out["affected_entities"]["item_ids"])
        fails = []
        if not has_items:
            for key in ("expected_total_brl", "difference_brl", "reconciled"):
                if pr[key] is not None:
                    fails.append(
                        GateFailure("NULL_HANDLING",
                                    f"order khong co item nhung {key} != null",
                                    "payment")
                    )
            for key, arr in (
                ("seller_ids", out["affected_entities"]["seller_ids"]),
                ("product_ids", out["product_context"]["product_ids"]),
                ("category_names", out["product_context"]["category_names"]),
                ("seller_handoff_analysis",
                 out["delivery_analysis"]["seller_handoff_analysis"]),
            ):
                if arr:
                    fails.append(
                        GateFailure("NULL_HANDLING",
                                    f"order khong co item nhung {key} khong rong",
                                    "order_product")
                    )
        return fails

    # -- 6 -----------------------------------------------------------------
    @staticmethod
    def _gate_rounding(out: dict[str, Any]) -> list[GateFailure]:
        fails = []

        def check(value: Any, label: str) -> None:
            if isinstance(value, float) and round(value, 2) != value:
                fails.append(
                    GateFailure("ROUNDING", f"{label}={value} qua 2 chu so", "core")
                )

        pr = out["payment_reconciliation"]
        for k in ("item_total_brl", "freight_total_brl", "expected_total_brl",
                  "payment_total_brl", "difference_brl"):
            check(pr[k], k)
        check(out["financial_resolution"]["recommended_refund_brl"], "refund")
        da = out["delivery_analysis"]
        check(da["delivery_variance_hours"], "delivery_variance_hours")
        for s in da["seller_handoff_analysis"]:
            check(s["handoff_variance_hours"], "handoff_variance_hours")
        return fails

    # -- 7 -----------------------------------------------------------------
    @staticmethod
    def _gate_timestamp(out: dict[str, Any]) -> list[GateFailure]:
        fails = []
        da = out["delivery_analysis"]
        candidates = [
            ("delivered_at", da["delivered_at"]),
            ("estimated_delivery_at", da["estimated_delivery_at"]),
            ("carrier_handoff_at", da["carrier_handoff_at"]),
        ] + [
            ("shipping_limit_at", s["shipping_limit_at"])
            for s in da["seller_handoff_analysis"]
        ]
        for label, value in candidates:
            if value is not None and not TS_PATTERN.match(str(value)):
                fails.append(
                    GateFailure("TIMESTAMP", f"{label}='{value}' sai dinh dang", "core")
                )
        return fails

    # -- 8 -----------------------------------------------------------------
    @staticmethod
    def _gate_status_consistency(out: dict[str, Any]) -> list[GateFailure]:
        refund = out["financial_resolution"]["recommended_refund_brl"] or 0
        status = out["case_assessment"]["case_status"]
        expected = "action_required" if refund > 0 else "no_action"
        if status != expected:
            return [
                GateFailure("STATUS_CONSISTENCY",
                            f"refund={refund} nhung case_status='{status}'", "policy")
            ]
        return []

    # -- 9 -----------------------------------------------------------------
    @staticmethod
    def _gate_action_order(out: dict[str, Any]) -> list[GateFailure]:
        actions = out["resolution_actions"]
        primary = out["case_assessment"]["primary_issue"]
        fails = []
        if not actions:
            return [GateFailure("ACTION_ORDER", "resolution_actions rong", "policy")]
        if actions[0] != PRIMARY_ACTION_OF.get(primary):
            fails.append(
                GateFailure("ACTION_ORDER",
                            f"action dau '{actions[0]}' khong khop primary "
                            f"'{primary}'", "policy")
            )
        if primary == "valid_split_payment" and "verify_payment_allocation" in actions:
            fails.append(
                GateFailure("ACTION_ORDER",
                            "valid_split_payment khong duoc co "
                            "verify_payment_allocation", "policy")
            )
        if "review_seller_handoff" in actions and "review_carrier_delay" in actions:
            fails.append(
                GateFailure("ACTION_ORDER",
                            "review_seller_handoff va review_carrier_delay loai tru "
                            "nhau", "policy")
            )
        return fails

    # -- 10 ----------------------------------------------------------------
    @staticmethod
    def _gate_secondary_order(out: dict[str, Any]) -> list[GateFailure]:
        issues = out["case_assessment"]["secondary_issues"]
        unknown = [i for i in issues if i not in SECONDARY_ORDER]
        if unknown:
            return [
                GateFailure("SECONDARY_ORDER", f"secondary la {unknown}", "policy")
            ]
        expected = [i for i in SECONDARY_ORDER if i in issues]
        if issues != expected:
            return [
                GateFailure("SECONDARY_ORDER",
                            f"sai thu tu: {issues} != {expected}", "policy")
            ]
        return []

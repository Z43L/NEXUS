from typing import Dict, Any
from loguru import logger
from decimal import Decimal
from .simulated_treasury import SimulatedTreasury
from ..marketplace.marketplace_contract import SimulatedMarketplaceContract

# En una implementación real, se importarían los componentes del sistema
# que la gobernanza puede modificar.
# from ..economics.slashing import SlashingMechanism
# from ..economics.emission_controller import ControlledEmissionModel
# from ..core.memory.shard_manager import ShardManager

class ProposalExecutionEngine:
    """
    Motor de ejecución para propuestas de gobernanza aprobadas.
    Este módulo es el "brazo ejecutor" de la DAO, aplicando los cambios
    en los componentes correspondientes del sistema.
    """
    def __init__(self, economic_engine, slashing_mechanism, memory_manager, treasury: SimulatedTreasury, marketplace: SimulatedMarketplaceContract):
        # Se inyectarían las instancias de los componentes que la
        # gobernanza puede modificar. Aquí se usan placeholders.
        self.economic_engine = economic_engine
        self.slashing_mechanism = slashing_mechanism
        self.memory_manager = memory_manager
        self.treasury = treasury
        self.marketplace = marketplace
        logger.info("Motor de Ejecución de Propuestas inicializado.")

    async def execute(self, proposal_type: str, payload: Dict[str, Any]) -> bool:
        """
        Punto de entrada para ejecutar una propuesta.
        Delega la ejecución al método apropiado basado en el tipo de propuesta.
        """
        execution_method_name = f"_execute_{proposal_type.lower()}"
        execution_method = getattr(self, execution_method_name, None)

        if not execution_method:
            logger.error(f"No hay un método de ejecución para el tipo de propuesta: {proposal_type}")
            return False

        try:
            logger.info(f"Ejecutando propuesta de tipo '{proposal_type}' con payload: {payload}")
            await execution_method(payload)
            logger.success(f"Propuesta de tipo '{proposal_type}' ejecutada exitosamente.")
            return True
        except Exception as e:
            logger.opt(exception=True).error(f"Falló la ejecución de la propuesta de tipo '{proposal_type}': {e}")
            return False

    async def _execute_parameter_change(self, payload: Dict[str, Any]):
        """
        Ejecuta un cambio de parámetro en un componente del sistema.
        Payload esperado: {"component": "slashing", "parameter": "base_slash_rates.malicious_action", "new_value": "0.1"}
        """
        component_name = payload.get("component")
        parameter_path = payload.get("parameter")
        new_value = payload.get("new_value")

        if not all([component_name, parameter_path, new_value is not None]):
            raise ValueError("Payload de cambio de parámetro inválido. Faltan 'component', 'parameter' o 'new_value'.")

        component_map = {
            "slashing": self.slashing_mechanism,
            "economics": self.economic_engine,
            "memory": self.memory_manager
            # "treasury" no es un componente modificable directamente, sino a través de operaciones.
        }
        target_component = component_map.get(component_name)

        if not target_component:
            raise ValueError(f"Componente '{component_name}' no encontrado o no es gobernable.")

        keys = parameter_path.split('.')
        attr = target_component
        for key in keys[:-1]:
            attr = getattr(attr, key)
        
        final_key = keys[-1]
        current_value = getattr(attr, final_key)
        if isinstance(current_value, Decimal):
            new_value = Decimal(new_value)

        setattr(attr, final_key, new_value)
        logger.info(f"Parámetro '{parameter_path}' en componente '{component_name}' actualizado a '{new_value}'.")

    async def _execute_treasury_management(self, payload: Dict[str, Any]):
        """
        Ejecuta una operación de la tesorería.
        Payload esperado: {"operation": "transfer", "asset": "NEX", "amount": "10000", "recipient": "grant_address"}
        """
        operation = payload.get("operation")

        if operation == "transfer":
            asset = payload.get("asset")
            amount_str = payload.get("amount")
            recipient = payload.get("recipient")

            if not all([asset, amount_str, recipient]):
                raise ValueError("Payload de transferencia de tesorería inválido. Faltan 'asset', 'amount' o 'recipient'.")

            amount = Decimal(amount_str)
            
            success = await self.treasury.transfer_funds(
                asset=asset, amount=amount, recipient=recipient
            )
            
            if not success:
                raise RuntimeError(f"La transferencia de la tesorería de {amount} {asset} a {recipient} falló, probablemente por fondos insuficientes.")
        else:
            raise ValueError(f"Operación de tesorería no soportada: '{operation}'")

    async def _execute_ecosystem_funding(self, payload: Dict[str, Any]):
        """
        Ejecuta una propuesta de financiamiento del ecosistema, como comprar un activo del marketplace.
        Payload esperado: {"operation": "acquire_asset", "listing_id": "listing_...", "purpose": "Public dataset for research"}
        """
        operation = payload.get("operation")

        if operation == "acquire_asset":
            listing_id = payload.get("listing_id")
            if not listing_id:
                raise ValueError("Payload de adquisición de activo inválido. Falta 'listing_id'.")

            listing = await self.marketplace.get_listing(listing_id)
            if not listing:
                raise ValueError(f"El listado '{listing_id}' no fue encontrado en el marketplace.")

            logger.info(f"La gobernanza aprobó la adquisición del activo '{listing.asset.name}' (ID: {listing_id}) para la comunidad.")

            # 1. Transferir fondos desde la tesorería al vendedor
            transfer_success = await self.treasury.transfer_funds(asset="NEX", amount=listing.price_nexus, recipient=listing.asset.owner_did)
            if not transfer_success:
                raise RuntimeError("La transferencia de fondos desde la tesorería para adquirir el activo falló.")

            # 2. Marcar el activo como comprado por la DAO
            await self.marketplace.delist_asset_as_sold(listing_id, purchaser_did="nexus_dao_treasury")
            logger.success(f"Activo '{listing.asset.name}' adquirido exitosamente por la DAO.")

    async def _execute_protocol_upgrade(self, payload: Dict[str, Any]):
        """Ejecuta una actualización de protocolo (placeholder)."""
        logger.info(f"Ejecutando actualización de protocolo: {payload}")

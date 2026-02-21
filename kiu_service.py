"""
Servicio de integración con la API de KIU (Sistema de Reservas de Vuelos)
API de Cervo Travel - ACTUALIZADO con documentación completa
"""
import requests
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)


class KiuService:
    """Servicio para interactuar con la API de KIU/Cervo Travel"""
    
    def __init__(self):
        self.base_url = Config.KIU_API_URL
        self.headers = {
            'Authorization': f'Bearer {Config.KIU_API_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def _make_request(self, method: str, endpoint: str, data: dict = None, params: dict = None, timeout: int = 30, extra_headers: dict = None):
        """Realiza una petición a la API de KIU"""
        try:
            url = f"{self.base_url}/{endpoint}"
            
            logger.info(f"KIU API Request: {method} {url}")
            if params:
                logger.info(f"Request params: {params}")
            if data:
                logger.debug(f"Request data: {data}")
            
            request_headers = self.headers.copy()
            if extra_headers:
                request_headers.update(extra_headers)

            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=request_headers,
                timeout=timeout
            )
            
            logger.info(f"KIU API Response: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                # Log solo resumen para evitar logs enormes con HTML entities
                if isinstance(response_data, dict):
                    if 'departureFlight' in response_data:
                        logger.info(f"KIU API Response: {len(response_data.get('departureFlight', []))} vuelos encontrados")
                    elif 'sesion_json' in response_data:
                        logger.info(f"KIU API Response: Reserva creada exitosamente")
                    elif 'loc' in response_data:
                        loc_data = response_data.get('loc', {})
                        logger.info(f"KIU API Response: PNR Status - Localizador: {loc_data.get('localizador', 'N/A')}")
                    else:
                        logger.info(f"KIU API Response: Datos recibidos correctamente")
                return {'success': True, 'data': response_data}
            else:
                error_msg = "Error de API"
                try:
                    error_json = response.json()
                    error_msg = error_json.get('message', f"Error {response.status_code}")
                    # Log completo del error para debugging
                    logger.error(f"KIU API Error Response: {error_json}")
                except:
                    error_msg = f"Error {response.status_code}: {response.text[:200]}"
                logger.error(f"KIU API Error {response.status_code}: {error_msg}")
                return {'success': False, 'error': error_msg, 'status_code': response.status_code}
                
        except requests.exceptions.Timeout:
            logger.warning(f"KIU API: Timeout después de {timeout}s")
            return {'success': False, 'error': f'Timeout después de {timeout} segundos. Intenta de nuevo.', 'timeout': True}
        except Exception as e:
            logger.warning(f"KIU API Exception: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # ========================================================================
    # ENDPOINT DE BÚSQUEDA DE VUELOS (NUEVO)
    # ========================================================================
    
    def search_flights(self, origin: str, destination: str, departure_date: str, 
                      adults: int = 1, children: int = 0, infants: int = 0,
                      return_date: str = None, currency: str = "USD", only_avails: bool = True,
                      from_cache: bool = True):
        """
        Busca vuelos disponibles con reintentos automáticos
        Endpoint: GET /v1/shopping/flights
        
        Args:
            origin: Código IATA origen (ej: "CCS", "PMV")
            destination: Código IATA destino (ej: "CCS", "PMV")
            departure_date: Fecha de salida "YYYY-MM-DD"
            adults: Número de adultos (default: 1)
            children: Número de niños (default: 0)
            infants: Número de infantes (default: 0)
            return_date: Fecha de regreso "YYYY-MM-DD" (opcional)
            currency: Moneda (default: "USD")
            only_avails: Solo vuelos disponibles (default: True)
        
        Returns:
            {
                "success": bool,
                "data": [...],  # Lista de vuelos disponibles
                "error": str  # Si hay error
            }
        """
        endpoint = "shopping/flights"
        
        logger.info(f"Searching flights: {origin} -> {destination} on {departure_date}")
        
        # Intentar con diferentes configuraciones si la primera falla
        # TIMEOUTS OPTIMIZADOS: Aumentados drásticamente para evitar falsos negativos en rutas lentas
        configs = [
            {"fromCache": "true", "onlyAvails": "false", "timeout": 45},  # Cache: 45s
            {"fromCache": "false", "onlyAvails": "false", "timeout": 90},  # Live: 90s (máximo posible)
        ]
        
        last_error = None
        
        for i, config in enumerate(configs):
            try:
                params = {
                    "gds": "kiu",
                    "originLocationCode": origin.upper(),
                    "destinationLocationCode": destination.upper(),
                    "departureDate": departure_date,
                    "adults": adults,
                    "currency": currency,
                    "onlyAvails": config["onlyAvails"],
                    "fromCache": config["fromCache"]
                }
                
                # Agregar parámetros opcionales
                if return_date:
                    params["returnDate"] = return_date
                else:
                    params["returnDate"] = ""
                
                if children > 0:
                    params["children"] = children
                
                if infants > 0:
                    params["infants"] = infants
                
                logger.info(f"Intento {i+1}/2 - fromCache={config['fromCache']}, onlyAvails={config['onlyAvails']}")
                
                result = self._make_request("GET", endpoint, params=params, timeout=config["timeout"])
                
                if result.get('success'):
                    data = result.get('data', {})
                    flights = data.get('departureFlight', [])
                    
                    if flights and len(flights) > 0:
                        logger.info(f"Búsqueda exitosa en intento {i+1}: {len(flights)} vuelos encontrados")
                        return result
                    else:
                        logger.warning(f"Intento {i+1} exitoso pero sin vuelos, probando otra config...")
                        last_error = "No hay vuelos en la respuesta"
                        continue
                else:
                    last_error = result.get('error', 'Error desconocido')
                    logger.warning(f"Intento {i+1} falló: {last_error}")
                    
                    # Si es timeout, esperar un poco antes de reintentar
                    if result.get('timeout'):
                        import time
                        time.sleep(2)
                    continue
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Excepción en intento {i+1}: {last_error}")
                continue
        
        # Si todos los intentos fallaron
        logger.error(f"Todos los intentos de búsqueda fallaron. Último error: {last_error}")
        return {'success': False, 'error': last_error or 'No se encontraron vuelos después de múltiples intentos'}
    
    # ========================================================================
    # ENDPOINTS DE PRICING Y BOOKING (ACTUALIZADOS)
    # ========================================================================
    
    def get_flight_pricing(self, departure_flight: dict, return_flight: dict = None, occupation: list = None):
        """
        Cotiza un vuelo específico
        Endpoint: POST /v1/kiu/flight-offers/pricing
        
        Args:
            departure_flight: Objeto completo con datos del vuelo de ida
                Debe incluir: order, isDirect, currency, currency_id, segmentsSize, segments[], etc.
            return_flight: Objeto completo con datos del vuelo de vuelta (opcional)
            occupation: Lista con tipos de pasajeros y clases por segmento
                Ejemplo: [{"type": "ADT", "segments": {"ES_8314_070000": "G"}}]
        
        La estructura de departure_flight debe incluir TODOS los campos:
        - order, isDirect, currency, currency_id, segmentsSize
        - segments[]: id, departureCode, arrivalCode, flightNumber, journeyDuration,
          departureDateTime, arrivalDateTime, departureDate, arrivalDate,
          departureTime, arrivalTime, stopQuantity, airEquipType, airlineCode,
          mealCode, meal, busy, class, classes{}, marketingCabins{},
          cabins{}, price, rates{}, airlineName, uid, base, breakdown[], baggage[]
        - departure, destination, price, rates{}, com, api, alt, airlines[],
          international, busy, id, base, breakdown[], baggage[], selected
        """
        endpoint = "kiu/flight-offers/pricing"
        
        data = {
            "departureFlight": departure_flight,
            "returnFlight": return_flight,
            "occupation": occupation or []
        }
        
        return self._make_request("POST", endpoint, data=data)
    
    def create_booking(self, departure_flight: dict, passengers: list, occupation: list,
                      return_flight: dict = None, observations: str = "", ticket_time_limit: int = None,
                      user_phone: str = None):
        """
        Crea una reservación (PNR)
        Endpoint: POST /v1/kiu/flight-offers/booking
        
        Args:
            departure_flight: Objeto completo del vuelo de ida (mismo que en pricing)
            passengers: Lista de pasajeros con estructura completa
            occupation: Lista con ocupación por tipo
            return_flight: Objeto del vuelo de vuelta (opcional)
            observations: Observaciones de la reserva
            ticket_time_limit: Límite de tiempo para emisión (horas)
            user_phone: Teléfono del usuario que realiza la reserva (para header X-User-Phone)
        
        Returns:
            {
                "success": True/False,
                "data": {
                    "vid": int,  # ID del viaje
                    "sesion_json": {
                        "vuelo": [{
                            "loc": str  # PNR
                            ...
                        }]
                    }
                }
            }
        """
        endpoint = "kiu/flight-offers/booking"
        
        data = {
            "departureFlight": departure_flight,
            "returnFlight": return_flight,
            "passengers": passengers,
            "observations": observations,
            "occupation": occupation
        }
        
        if ticket_time_limit is not None:
            data["ticketTimeLimit"] = ticket_time_limit
            
        extra_headers = {}
        if user_phone:
            extra_headers['X-User-Phone'] = user_phone
        
        # Timeout de 90 segundos para crear reservas (aumentado para evitar timeouts)
        return self._make_request("POST", endpoint, data=data, timeout=90, extra_headers=extra_headers)
    
    # ========================================================================
    # ENDPOINTS DE CONSULTA
    # =======================================================================
    
    def get_purchase_data(self, vid: int = None, pnr: str = None, reemision: bool = True,
                         package_status=None, antiquity_days=None, page: int = 1):
        """
        Obtiene datos de una compra/reservación
        Endpoint: POST /v1/purchases
        
        Args:
            vid: ID del viaje (viaje_id)
            pnr: Código PNR (se pasa como query param)
            reemision: Si es reemisión
            package_status: Estado del paquete
            antiquity_days: Antigüedad en días
            page: Página de resultados
        """
        endpoint = "purchases"
        params = {"reemision": "true" if reemision else "false"}
        
        # Si se proporciona PNR, va como query param
        if pnr:
            params["pnr"] = pnr.upper()
            data = None
        else:
            # Si se proporciona VID, va en el body
            data = {
                "packageStatus": package_status,
                "vid": vid,
                "antiquityDays": antiquity_days,
                "page": page
            }
        
        return self._make_request("POST", endpoint, data=data, params=params)
    
    def get_booking_status_by_viaje_id(self, viaje_id: str):
        """
        Consulta el estatus de una reservación por ID de viaje
        Endpoint: GET /v1/purchases/{viaje_id}/flight/status
        
        Args:
            viaje_id: ID del viaje (vid)
        """
        endpoint = f"purchases/{viaje_id}/flight/status"
        return self._make_request("GET", endpoint)
    
    def get_booking_status(self, pnr: str):
        """
        Consulta el estatus de una reservación por PNR
        
        Endpoint: GET /v1/kiu/flight/status/{PNR}?alt=2
        
        Args:
            pnr: Código de localizador (PNR) de 6 caracteres
        
        Returns:
            Datos completos de la reservación incluyendo pasajeros, vuelos y precios
        """
        endpoint = f"kiu/flight/status/{pnr.upper()}"
        # Timeout aumentado a 20 segundos para consultas PNR (dar más tiempo a la API)
        return self._make_request("GET", endpoint, params={"alt": 2}, timeout=20)
    
    # ========================================================================
    # ENDPOINTS DE GESTIÓN DE RESERVAS
    # ========================================================================
    
    def rebook_flight(self, flight_order_id: str, vue: int = 0):
        """
        Retoma una reserva de vuelo
        Endpoint: POST /v1/booking/flight-orders/{order_id}/rebook?vue=0
        
        Args:
            flight_order_id: ID de la orden de vuelo (vid)
            vue: Parámetro vue (servicio_id que va a ser retomado)
        
        Returns:
            {
                "vid": int,  # Nuevo ID de viaje
                "sesion_json": {
                    "vuelo": [...]
                }
            }
        """
        endpoint = f"booking/flight-orders/{flight_order_id}/rebook"
        return self._make_request("POST", endpoint, params={"vue": vue})
    
    def post_remission(self, viaje_id: str, purchase_data: dict):
        """
        Crea una remisión
        Endpoint: POST /v1/purchases/{viaje_id}/remission
        
        Args:
            viaje_id: ID del viaje
            purchase_data: Datos de la compra (completos)
        """
        endpoint = f"purchases/{viaje_id}/remission"
        return self._make_request("POST", endpoint, data=purchase_data)
    
    # ========================================================================
    # ENDPOINTS DE CLIENTES
    # ========================================================================
    
    def search_client(self, value: str, field: str = "nombre", filter_type: str = "contains"):
        """
        Busca un cliente
        Endpoint: POST /v1/clients/search
        
        Args:
            value: Valor a buscar
            field: Campo donde buscar ("nombre", "email", "telefono_movil", etc.)
            filter_type: Tipo de filtro ("contains", "equals", etc.)
        
        Returns:
            Lista de clientes encontrados con:
            - cid: ID del cliente
            - nombre, apellido, email
            - pais_id, estado
            - telefono_fijo, telefono_movil
            - titulo
        """
        endpoint = "clients/search"
        data = {
            "field": field,
            "filter": filter_type,
            "value": value
        }
        return self._make_request("POST", endpoint, data=data)
    
    def confirm_client(self, vid: int, client_id: int):
        """
        Asigna un cliente a una orden de vuelo
        Endpoint: POST /v1/booking/flight-orders/confirm-client
        
        Args:
            vid: ID del viaje
            client_id: ID del cliente (cid)
        """
        endpoint = "booking/flight-orders/confirm-client"
        data = {
            "vid": vid,
            "client_id": client_id
        }
        return self._make_request("POST", endpoint, data=data)
    
    # ========================================================================
    # MÉTODOS DE UTILIDAD
    # ========================================================================
    
    def build_segment(self, airline_code: str, flight_number: str,
                     departure_code: str, arrival_code: str,
                     departure_datetime: str, arrival_datetime: str,
                     flight_class: str, price: float = 0, 
                     rates: dict = None, **kwargs):
        """
        Construye un objeto de segmento de vuelo con la estructura completa requerida
        
        NOTA: Este método es un helper, pero la información de vuelos
        debe obtenerse de alguna fuente externa (no hay endpoint de búsqueda)
        
        Args:
            airline_code: Código de aerolínea (ej: "ES", "5R")
            flight_number: Número de vuelo
            departure_code: Código IATA origen
            arrival_code: Código IATA destino
            departure_datetime: Fecha/hora salida "YYYY-MM-DD HH:MM:SS"
            arrival_datetime: Fecha/hora llegada "YYYY-MM-DD HH:MM:SS"
            flight_class: Clase de vuelo
            price: Precio del segmento
            rates: Diccionario con tasas
            **kwargs: Otros campos opcionales
        
        Returns:
            Diccionario con estructura completa de segmento
        """
        dep_dt = datetime.strptime(departure_datetime, "%Y-%m-%d %H:%M:%S")
        arr_dt = datetime.strptime(arrival_datetime, "%Y-%m-%d %H:%M:%S")
        
        duration = arr_dt - dep_dt
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        journey_duration = f"{int(hours):02d}:{int(minutes):02d}:00"
        
        segment_id = f"{airline_code}_{flight_number}_{dep_dt.strftime('%H%M%S')}"
        
        segment = {
            "id": segment_id,
            "departureCode": departure_code,
            "arrivalCode": arrival_code,
            "flightNumber": flight_number,
            "journeyDuration": journey_duration,
            "departureDateTime": departure_datetime,
            "arrivalDateTime": arrival_datetime,
            "departureDate": dep_dt.strftime("%Y-%m-%d"),
            "arrivalDate": arr_dt.strftime("%Y-%m-%d"),
            "departureTime": dep_dt.strftime("%H:%M:%S"),
            "arrivalTime": arr_dt.strftime("%H:%M:%S"),
            "stopQuantity": "0",
            "airEquipType": kwargs.get("airEquipType", "733"),
            "airlineCode": airline_code,
            "mealCode": kwargs.get("mealCode", "N"),
            "meal": kwargs.get("meal", "(N)"),
            "busy": 0,
            "class": flight_class,
            "classes": kwargs.get("classes", {flight_class: "9"}),
            "marketingCabins": kwargs.get("marketingCabins", {flight_class: "1"}),
            "cabins": kwargs.get("cabins", {"1": "Economy"}),
            "price": price,
            "rates": rates or {},
            "airlineName": kwargs.get("airlineName", ""),
            "uid": kwargs.get("uid", ""),
            "base": rates.get("base", 0) if rates else 0,
            "breakdown": kwargs.get("breakdown", []),
            "baggage": kwargs.get("baggage", [])
        }
        
        return segment
    
    def health_check(self):
        """Verifica el estado de la API"""
        try:
            # Intentar obtener datos de compra sin parámetros
            result = self.get_purchase_data(page=1)
            if result.get('success', False):
                return {'success': True, 'message': 'API funcionando correctamente'}
            else:
                return {'success': False, 'error': 'API no respondió correctamente'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_national_airports(self):
        """
        Obtiene la lista de aeropuertos nacionales
        Endpoint: GET /v1/iata-codes/national
        
        Returns:
            {
                "success": bool,
                "data": [...],  # Lista de aeropuertos
                "error": str  # Si hay error
            }
        """
        endpoint = "iata-codes/national"
        return self._make_request("GET", endpoint, timeout=30)
    
    def get_international_airports(self):
        """
        Obtiene la lista de aeropuertos internacionales
        Endpoint: GET /v1/iata-codes/international
        
        Returns:
            {
                "success": bool,
                "data": [...],  # Lista de aeropuertos
                "error": str  # Si hay error
            }
        """
        endpoint = "iata-codes/international"
        return self._make_request("GET", endpoint, timeout=30)


# Instancia global
kiu_service = KiuService()

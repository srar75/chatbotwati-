"""
Servicio COMPLETO con API REAL de KIU
Usa el endpoint GET /shopping/flights para buscar vuelos
"""
from datetime import datetime
from typing import List, Dict, Optional
from kiu_service import kiu_service
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class FlightBookingServiceComplete:
    """
    Servicio 100% con API de KIU
    - Búsqueda: GET /shopping/flights (API REAL)
    - Cotización: POST /pricing (API REAL)
    - Reserva: POST /booking (API REAL)
    """
    
    def __init__(self):
        self.kiu = kiu_service
    
    def search_flights(self, origin: str, destination: str, date: str, 
                      passengers: Dict[str, int] = None, currency: str = "USD") -> List[Dict]:
        """
        Busca vuelos disponibles en la API REAL de KIU
        
        Args:
            origin: Código IATA origen (ej: "CCS", "PMV")
            destination: Código IATA destino
            date: Fecha "YYYY-MM-DD" o "DD/MM/YYYY"
            passengers: {"ADT": 1, "CHD": 0, "INF": 0}
            currency: Moneda para precios ("USD" o "BS")
        
        Returns:
            Lista de vuelos con precios reales de la API
        """
        try:
            # Normalizar fecha
            date_normalized = self._normalize_date(date)
            
            # Pasajeros por defecto
            if not passengers:
                passengers = {"ADT": 1, "CHD": 0, "INF": 0}
            
            adults = passengers.get("ADT", 1)
            children = passengers.get("CHD", 0)
            infants = passengers.get("INF", 0)
            
            logger.info(f"Searching flights: {origin} -> {destination} on {date_normalized}")
            
            # Llamar al endpoint REAL de búsqueda con reintentos
            result = None
            max_retries = 2
            
            for attempt in range(1, max_retries + 1):
                try:
                    result = self.kiu.search_flights(
                        origin=origin,
                        destination=destination,
                        departure_date=date_normalized,
                        adults=adults,
                        children=children,
                        infants=infants,
                        currency="USD",
                        only_avails=False,  # TODOS los vuelos, no solo disponibles
                        from_cache=True
                    )
                    
                    if result.get('success'):
                        break  # Éxito, salir del loop
                    
                    # Si falló, reintentar
                    if attempt < max_retries:
                        logger.warning(f"Intento {attempt} falló, reintentando...")
                        import time
                        time.sleep(1)
                except Exception as e:
                    logger.warning(f"Error en intento {attempt}: {str(e)}")
                    if attempt < max_retries:
                        import time
                        time.sleep(1)
                    else:
                        result = {"success": False, "error": str(e)}
            
            if not result or not result.get('success'):
                logger.error(f"Search failed: {result.get('error') if result else 'No response'}")
                return []
            
            # Procesar respuesta de la API
            api_data = result.get('data', {})
            departure_flights = api_data.get('departureFlight', [])
            
            # Log resumido para evitar HTML entities
            logger.info(f"API Response - Total flights: {len(departure_flights)}")
            
            if not departure_flights:
                logger.info("No flights found")
                return []
            
            # FASE 1: Procesar vuelos y obtener SOLO 1 precio por vuelo (el más barato)
            flight_options = []
            flights_needing_pricing = []  # Lista de (flight_option, flight_data, segment_id, available_classes)
            
            for flight_data in departure_flights:
                try:
                    # Obtener primer segmento (vuelo directo)
                    segments = flight_data.get('segments', [])
                    if not segments:
                        continue
                    
                    segment = segments[0]
                    
                    # Obtener precio real del vuelo
                    price = flight_data.get('price')
                    base = flight_data.get('base')
                    
                    # Si no hay precio, intentar obtenerlo del segmento
                    if not price:
                        price = segment.get('price')
                    
                    # Si aún no hay precio, intentar obtenerlo de rates
                    if not price:
                        rates = segment.get('rates', {})
                        if rates:
                            price = rates.get('total') or rates.get('price')

                    # Limpiar precio y base si son listas
                    if isinstance(price, list) and len(price) > 0:
                        price = price[0]
                    if isinstance(base, list) and len(base) > 0:
                        base = base[0]
                    
                    # Calcular duración total
                    total_duration = flight_data.get('journeyDuration', '')
                    if not total_duration and segments:
                        total_minutes = 0
                        for seg in segments:
                            seg_duration = seg.get('journeyDuration', '')
                            if seg_duration:
                                parts = seg_duration.split(':')
                                if len(parts) >= 2:
                                    total_minutes += int(parts[0]) * 60 + int(parts[1])
                        if total_minutes > 0:
                            hours = total_minutes // 60
                            minutes = total_minutes % 60
                            total_duration = f"{hours:02d}:{minutes:02d}:00"
                    
                    # Guardar las clases disponibles
                    classes = segment.get('classes', {})
                    segment_id = segment.get('id')
                    
                    flight_option = {
                        "flight_id": segment_id,
                        "airline": segment.get('airlineCode'),
                        "airline_name": segment.get('airlineName', segment.get('airlineCode')),
                        "flight_number": segment.get('flightNumber'),
                        "origin": segment.get('departureCode'),
                        "destination": segment.get('arrivalCode'),
                        "date": date_normalized,
                        "departure_time": segment.get('departureTime', '').split(':')[0] + ':' + segment.get('departureTime', '').split(':')[1] if segment.get('departureTime') else '',
                        "arrival_time": segment.get('arrivalTime', '').split(':')[0] + ':' + segment.get('arrivalTime', '').split(':')[1] if segment.get('arrivalTime') else '',
                        "duration": total_duration,
                        "class": segment.get('class'),
                        "aircraft": segment.get('airEquipType'),
                        "price": price[0] if isinstance(price, list) else price,
                        "base": (base[0] if isinstance(base, list) else base) or 0,
                        "currency": "USD",
                        "passengers": passengers,
                        "available_classes": classes,  # Guardar clases disponibles para pricing posterior
                        "api_data": flight_data,
                        "source": "API_KIU_SEARCH"
                    }

                    
                    # Si tiene precio válido, agregar directamente
                    if price and price > 0:
                        flight_options.append(flight_option)
                        logger.info(f"Added flight: {flight_option['airline']}{flight_option['flight_number']} - ${price}")
                    elif classes and segment_id:
                        # Necesita pricing SOLO para la clase más barata
                        flights_needing_pricing.append((flight_option, flight_data, segment_id, classes))
                    else:
                        logger.warning(f"Skipped flight {flight_option.get('airline', '')}{flight_option.get('flight_number', '')} - no valid price")
                    
                except Exception as e:
                    logger.error(f"Error processing flight: {str(e)}")
                    continue
            
            # FASE 2: Obtener SOLO 1 precio por vuelo (la clase más económica)
            if flights_needing_pricing:
                logger.info(f"Obteniendo precio más barato para {len(flights_needing_pricing)} vuelos...")
                
                def get_cheapest_price(args):
                    """Obtiene el precio de la clase más económica"""
                    flight_option, flight_data, segment_id, available_classes, flight_idx = args
                    try:
                        # Prioridad de clases económicas
                        priority_classes = ['T', 'V', 'W', 'X', 'S', 'U', 'Q', 'O', 'N', 'L', 'K', 'M', 'E', 'A', 'Z', 'H', 'Y', 'B', 'R']
                        selected_class = None
                        for c in priority_classes:
                            if c in available_classes:
                                selected_class = c
                                break
                        if not selected_class:
                            selected_class = list(available_classes.keys())[0]
                        
                        occupation = [{"type": "ADT", "segments": {segment_id: selected_class}}]
                        
                        pricing_result = self.kiu.get_flight_pricing(
                            departure_flight=flight_data,
                            occupation=occupation
                        )
                        
                        if pricing_result.get('success'):
                            pricing_data = pricing_result.get('data', [])
                            if isinstance(pricing_data, list) and len(pricing_data) > 0:
                                price_value = pricing_data[0].get('price')
                                if isinstance(price_value, list) and len(price_value) > 0:
                                    price_value = price_value[0]
                                base_value = pricing_data[0].get('base', 0)
                                if isinstance(base_value, list) and len(base_value) > 0:
                                    base_value = base_value[0]
                                if price_value and price_value > 0:
                                    return (flight_idx, selected_class, price_value, base_value)
                    except Exception as e:
                        logger.debug(f"Error obteniendo precio: {str(e)}")
                    return (flight_idx, None, None, None)
                
                # Preparar tareas: UNA tarea por vuelo
                all_tasks = [(fo, fd, sid, ac, idx) for idx, (fo, fd, sid, ac) in enumerate(flights_needing_pricing)]
                
                logger.info(f"Total de llamadas de pricing: {len(all_tasks)} (1 por vuelo)")
                
                # Ejecutar pricing en paralelo (Ajustado para estabilidad: menos workers, más timeout)
                # 12 workers es suficiente para velocidad sin saturar la API
                with ThreadPoolExecutor(max_workers=12) as executor:
                    futures = {executor.submit(get_cheapest_price, task): task for task in all_tasks}
                    
                    try:
                        # Timeout global 90s
                        for future in as_completed(futures, timeout=90):
                            try:
                                # Timeout individual: 30s para dar tiempo a aerolíneas lentas
                                f_idx, class_code, price_value, base_value = future.result(timeout=30)
                                
                                if price_value and price_value > 0:
                                    flight_option = flights_needing_pricing[f_idx][0]
                                    flight_option['price'] = price_value
                                    flight_option['base'] = base_value
                                    flight_option['class'] = class_code
                                    logger.debug(f"Precio vuelo {f_idx}: ${price_value} (clase {class_code})")
                                    
                            except Exception as e:
                                logger.debug(f"Error en resultado de pricing: {str(e)}")
                    except Exception as e:
                        logger.warning(f"Timeout en pricing: {str(e)}")
                
                # FASE 3: Agregar vuelos que consiguieron precio
                for flight_option, _, _, _ in flights_needing_pricing:
                    if flight_option.get('price'):
                        flight_options.append(flight_option)
                        logger.info(f"Added flight: {flight_option['airline']}{flight_option['flight_number']} - ${flight_option['price']}")
            
            # Si no hay vuelos con precio, devolver lista vacía
            # Si no hay vuelos con precio, intentar ESTRATEGIA DE RESCATE (Fallback)
                if not flight_options and flights_needing_pricing:
                    logger.warning("Estrategia inicial falló (0 resultados). Iniciando ESTRATEGIA DE RESCATE (Baja Concurrencia)...")
                    
                    # Intentar rescatar hasta 15 vuelos (para cubrir "todos" o la mayoría)
                    # Usamos menos workers (4) para ser más amables con la API y evitar bloqueos
                    rescue_candidates = flights_needing_pricing[:15]
                    
                    # Reutilizamos la función get_cheapest_price pero en "Low Gear"
                    rescue_tasks = [(fo, fd, sid, ac, idx) for idx, (fo, fd, sid, ac) in enumerate(rescue_candidates)]
                    
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = {executor.submit(get_cheapest_price, task): task for task in rescue_tasks}
                        
                        try:
                            # Timeout global de rescate: 60s
                            for future in as_completed(futures, timeout=60):
                                try:
                                    # Timeout individual MUY generoso: 20s
                                    f_idx, class_code, price_value, base_value = future.result(timeout=20)
                                    
                                    if price_value and price_value > 0:
                                        flight_option = rescue_candidates[f_idx][0]
                                        flight_option['price'] = price_value
                                        flight_option['base'] = base_value
                                        flight_option['class'] = class_code
                                        flight_options.append(flight_option)
                                        logger.info(f"¡Vuelo rescatado! {flight_option['flight_number']} - ${price_value}")
                                except Exception as e:
                                    logger.error(f"Fallo en rescate individual: {e}")
                        except Exception as e:
                            logger.warning(f"Timeout global en rescate: {e}")
            
            if not flight_options:
                logger.warning("No se pudieron obtener precios para ningún vuelo (ni siquiera en rescate)")
                return []
            
            logger.info(f"Total vuelos encontrados: {len(flight_options)}")
            
            # Ordenar por hora de salida (MOSTRAR TODOS)
            flight_options.sort(key=lambda x: x['departure_time'])
            
            return flight_options
            
        except Exception as e:
            logger.error(f"Error searching flights: {str(e)}")
            return []
    
    def get_all_class_prices(self, flight_option: Dict) -> Dict:
        """
        Obtiene precios de TODAS las clases disponibles para un vuelo específico.
        Se llama DESPUÉS de que el usuario selecciona un vuelo.
        
        Args:
            flight_option: Diccionario con datos del vuelo seleccionado
        
        Returns:
            {"success": bool, "classes_prices": {"Y": {"price": 100, "base": 80}, ...}}
        """
        try:
            flight_data = flight_option.get('api_data')
            available_classes = flight_option.get('available_classes', {})
            
            # Logging detallado del vuelo seleccionado
            flight_number = flight_option.get('flight_number', 'N/A')
            airline = flight_option.get('airline_name', 'N/A')
            logger.info(f"=== COTIZANDO VUELO: {airline} {flight_number} ===")
            
            if not flight_data or not available_classes:
                return {"success": False, "error": "Datos de vuelo incompletos"}
            
            segments = flight_data.get('segments', [])
            if not segments:
                return {"success": False, "error": "No hay segmentos"}
            
            segment_id = segments[0].get('id')
            logger.info(f"Segment ID: {segment_id}")
            classes_prices = {}
            
            logger.info(f"Obteniendo precios de {len(available_classes)} clases para {airline} {flight_number}...")
            
            def get_class_price(class_code):
                try:
                    occupation = [{"type": "ADT", "segments": {segment_id: class_code}}]
                    result = self.kiu.get_flight_pricing(
                        departure_flight=flight_data,
                        occupation=occupation
                    )
                    if result.get('success'):
                        data = result.get('data', [])
                        if isinstance(data, list) and len(data) > 0:
                            price = data[0].get('price')
                            if isinstance(price, list) and len(price) > 0:
                                price = price[0]
                            base = data[0].get('base', 0)
                            if isinstance(base, list) and len(base) > 0:
                                base = base[0]
                            if price and price > 0:
                                return (class_code, price, base, available_classes.get(class_code, '0'))
                except Exception as e:
                    logger.debug(f"Error clase {class_code}: {str(e)}")
                return (class_code, None, None, None)
            
            # Ejecutar en paralelo
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(get_class_price, c): c for c in available_classes.keys()}
                
                try:
                    for future in as_completed(futures, timeout=45):
                        try:
                            class_code, price, base, avail = future.result(timeout=5)
                            if price:
                                classes_prices[class_code] = {
                                    'price': price,
                                    'base': base,
                                    'availability': avail
                                }
                                logger.info(f"Clase {class_code}: ${price}")
                        except Exception as e:
                            logger.debug(f"Error en resultado: {str(e)}")
                except Exception as e:
                    logger.warning(f"Timeout obteniendo precios: {str(e)}")
            
            if classes_prices:
                return {"success": True, "classes_prices": classes_prices}
            else:
                return {"success": False, "error": "No se pudieron obtener precios"}
                
        except Exception as e:
            logger.error(f"Error en get_all_class_prices: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_flight_pricing(self, origin: str = None, destination: str = None, 
                          date: str = None, flight_number: str = None,
                          departure_flight: dict = None, flight_class: str = "Y") -> Dict:
        """
        Obtiene el precio de un vuelo específico
        
        Args:
            origin: Código IATA origen
            destination: Código IATA destino
            date: Fecha del vuelo
            flight_number: Número de vuelo
            departure_flight: Datos completos del vuelo (de la API)
            flight_class: Clase a cotizar (default: Y)
        
        Returns:
            {"success": bool, "total_price": float, "breakdown": dict}
        """
        try:
            # Si tenemos los datos completos del vuelo
            if departure_flight:
                # Obtener el ID del segmento y construir ocupación correcta
                segments = departure_flight.get('segments', [])
                if segments:
                    segment_id = segments[0].get('id')
                    classes = segments[0].get('classes', {})
                    
                    # Usar la clase seleccionada si está disponible
                    if flight_class and flight_class in classes:
                        selected_class = flight_class
                    elif 'Y' in classes:
                        selected_class = 'Y'
                    else:
                        selected_class = list(classes.keys())[0] if classes else 'Y'
                    
                    occupation = [{"type": "ADT", "segments": {segment_id: selected_class}}]
                    
                    result = self.kiu.get_flight_pricing(
                        departure_flight=departure_flight,
                        return_flight=None,
                        occupation=occupation
                    )
                    
                    if result.get('success'):
                        data = result.get('data', [])
                        if isinstance(data, list) and len(data) > 0:
                            pricing_data = data[0]
                            return {
                                "success": True,
                                "total_price": pricing_data.get('price', 0),
                                "base_price": pricing_data.get('base', 0),
                                "breakdown": pricing_data.get('breakdown', []),
                                "currency": "USD"
                            }
            
            # Si no tenemos datos completos, buscar el vuelo primero
            if origin and destination and date:
                # Buscar vuelo en la API
                search_result = self.kiu.search_flights(
                    origin=origin,
                    destination=destination,
                    departure_date=self._normalize_date(date)
                )
                
                if search_result.get('success'):
                    api_data = search_result.get('data', {})
                    departure_flights = api_data.get('departureFlight', [])
                    
                    for flight_data in departure_flights:
                        segments = flight_data.get('segments', [])
                        if segments:
                            seg = segments[0]
                            seg_id = seg.get('id')
                            seg_flight_num = seg.get('flightNumber')
                            classes = seg.get('classes', {})
                            
                            # Si buscamos un vuelo específico, verificar
                            if flight_number and seg_flight_num != flight_number:
                                continue
                            
                            # Usar la clase más económica disponible (T, V, W, X, etc. antes de Y)
                            priority_classes = ['T', 'V', 'W', 'X', 'S', 'U', 'Q', 'O', 'N', 'L', 'K', 'M', 'E', 'A', 'Z', 'H', 'Y', 'B', 'R']
                            selected_class = None
                            for c in priority_classes:
                                if c in classes:
                                    selected_class = c
                                    break
                            if not selected_class:
                                selected_class = list(classes.keys())[0] if classes else 'Y'
                            occupation = [{"type": "ADT", "segments": {seg_id: selected_class}}]
                            
                            pricing_result = self.kiu.get_flight_pricing(
                                departure_flight=flight_data,
                                occupation=occupation
                            )
                            
                            if pricing_result.get('success'):
                                data = pricing_result.get('data', [])
                                if isinstance(data, list) and len(data) > 0:
                                    pricing_data = data[0]
                                    return {
                                        "success": True,
                                        "total_price": pricing_data.get('price', 0),
                                        "base_price": pricing_data.get('base', 0),
                                        "breakdown": pricing_data.get('breakdown', []),
                                        "currency": "USD"
                                    }
            
            return {"success": False, "error": "No se pudo obtener precio"}
            
        except Exception as e:
            logger.error(f"Error getting flight pricing: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def create_booking(self, flight_option: Dict, passenger_details: List[Dict], return_flight_option: Dict = None, user_phone: str = None) -> Dict:
        """
        Crea reservación usando datos del vuelo de la API.
        Si ida y vuelta son de aerolíneas DIFERENTES, crea DOS reservas separadas.
        Si son la MISMA aerolínea, crea una sola reserva.
        """
        try:
            # Extraer código de aerolínea del vuelo de IDA (priorizar api_data)
            ida_airline = None
            if flight_option.get('api_data'):
                segments = flight_option['api_data'].get('segments', [])
                if segments:
                    ida_airline = segments[0].get('airlineCode')
            if not ida_airline:
                ida_airline = flight_option.get('airline', '')
            
            # Extraer código de aerolínea del vuelo de VUELTA (priorizar api_data)
            vuelta_airline = None
            if return_flight_option:
                if return_flight_option.get('api_data'):
                    segments = return_flight_option['api_data'].get('segments', [])
                    if segments:
                        vuelta_airline = segments[0].get('airlineCode')
                if not vuelta_airline:
                    vuelta_airline = return_flight_option.get('airline', '')
            
            logger.info(f"🛩️ DEBUG - IDA airline: '{ida_airline}', VUELTA airline: '{vuelta_airline}'")
            logger.info(f"🛩️ DEBUG - return_flight_option exists: {return_flight_option is not None}")
            logger.info(f"🛩️ DEBUG - Airlines are different: {ida_airline != vuelta_airline}")
            
            # Si hay vuelo de vuelta y son aerolíneas DIFERENTES
            if return_flight_option and ida_airline and vuelta_airline and ida_airline != vuelta_airline:
                logger.info(f"⚠️ Aerolíneas diferentes detectadas: IDA={ida_airline}, VUELTA={vuelta_airline}")
                logger.info("Creando DOS reservas separadas...")
                
                # Crear reserva de IDA (sin vuelta)
                result_ida = self._create_single_booking(flight_option, passenger_details, None, user_phone=user_phone)
                
                if not result_ida.get('success'):
                    return {
                        "success": False,
                        "error": f"Error en reserva de IDA: {result_ida.get('error')}"
                    }
                
                pnr_ida = result_ida.get('pnr')
                vid_ida = result_ida.get('vid')
                logger.info(f"✅ Reserva IDA creada: PNR={pnr_ida}, VID={vid_ida}")
                
                # Crear reserva de VUELTA (sin ida)
                result_vuelta = self._create_single_booking(return_flight_option, passenger_details, None, user_phone=user_phone)
                
                if not result_vuelta.get('success'):
                    return {
                        "success": True,  # La de ida sí se creó
                        "partial": True,
                        "pnr": pnr_ida,
                        "pnr_ida": pnr_ida,
                        "vid": vid_ida,
                        "vid_ida": vid_ida,
                        "error_vuelta": f"Error en reserva de VUELTA: {result_vuelta.get('error')}",
                        "message": f"⚠️ ATENCIÓN: Solo se pudo crear la reserva de IDA.\n🎫 PNR IDA: {pnr_ida}\n❌ La reserva de VUELTA falló."
                    }
                
                pnr_vuelta = result_vuelta.get('pnr')
                vid_vuelta = result_vuelta.get('vid')
                logger.info(f"✅ Reserva VUELTA creada: PNR={pnr_vuelta}, VID={vid_vuelta}")
                
                # Retornar ambos PNR
                return {
                    "success": True,
                    "multiple_pnr": True,
                    "pnr": pnr_ida,  # PNR principal (ida)
                    "pnr_ida": pnr_ida,
                    "pnr_vuelta": pnr_vuelta,
                    "vid": vid_ida,
                    "vid_ida": vid_ida,
                    "vid_vuelta": vid_vuelta,
                    "airline_ida": ida_airline,
                    "airline_vuelta": vuelta_airline,
                    "message": f"✅ Reservas creadas exitosamente!\n\n🎫 PNR IDA ({ida_airline}): {pnr_ida}\n🎫 PNR VUELTA ({vuelta_airline}): {pnr_vuelta}"
                }
            
            # Si es la misma aerolínea o solo ida, crear una sola reserva
            return self._create_single_booking(flight_option, passenger_details, return_flight_option, user_phone=user_phone)
                
        except Exception as e:
            logger.error(f"Error creating booking: {str(e)}")
            return {"success": False, "error": str(e)}

    def _create_single_booking(self, flight_option: Dict, passenger_details: List[Dict], return_flight_option: Dict = None, user_phone: str = None) -> Dict:
        """
        Crea UNA reservación (usada internamente).
        """
        try:
            # 1. REFRESCAR VUELO DE IDA
            origin = flight_option.get('origin')
            destination = flight_option.get('destination')
            date = flight_option.get('date')
            flight_number = flight_option.get('flight_number')
            
            # DETERMINAR CUENTA REAL DE PASAJEROS POR TIPO
            # passengers = {"ADT": 1, "CHD": 0, "INF": 0}
            num_passengers = len(passenger_details) if passenger_details else 1
            passengers = {"ADT": 0, "CHD": 0, "INF": 0}
            
            if passenger_details:
                for p in passenger_details:
                    p_type = p.get('type', 'ADT').upper()
                    if p_type in passengers:
                        passengers[p_type] += 1
                    else:
                        passengers['ADT'] += 1
            else:
                passengers["ADT"] = 1
                
            logger.info(f"Pasajeros por tipo: {passengers}")
            requested_airline = flight_option.get('airline')
            requested_class = flight_option.get('class', 'Y')

            logger.info(f"Refrescando ida: {flight_number} de {requested_airline}")
            fresh_ida = self.search_flights(origin, destination, date, passengers)
            
            departure_flight_data = None
            for f in fresh_ida:
                if f.get('flight_number') == flight_number and (not requested_airline or f.get('airline') == requested_airline):
                    departure_flight_data = f.get('api_data')
                    break
            
            if not departure_flight_data:
                departure_flight_data = flight_option.get('api_data')
                logger.warning("Usando datos originales de ida (fallback)")

            # 2. REFRESCAR VUELO DE VUELTA (SI EXISTE)
            return_flight_data = None
            return_class = None
            r_flight_number = None
            if return_flight_option:
                r_origin = return_flight_option.get('origin')
                r_destination = return_flight_option.get('destination')
                r_date = return_flight_option.get('date')
                r_flight_number = return_flight_option.get('flight_number')
                r_airline = return_flight_option.get('airline')
                return_class = return_flight_option.get('class', 'Y')

                logger.info(f"Refrescando vuelta: {r_flight_number} de {r_airline}")
                fresh_vuelta = self.search_flights(r_origin, r_destination, r_date, passengers)
                
                for f in fresh_vuelta:
                    if f.get('flight_number') == r_flight_number and (not r_airline or f.get('airline') == r_airline):
                        return_flight_data = f.get('api_data')
                        break
                
                if not return_flight_data:
                    return_flight_data = return_flight_option.get('api_data')
                    logger.warning("Usando datos originales de vuelta (fallback)")

            # 3. FORMATEAR PASAJEROS
            passengers_formatted = []
            for pax in passenger_details:
                nationality = pax.get('nationality', 'VE')
                birth_country = pax.get('birthCountry', nationality)
                doc_issue_country = pax.get('docIssueCountry', nationality)
                doc_expiry = pax.get('docExpiry', '')
                
                # LÓGICA DE PREFIJOS DOCUMENTO CORREGIDA (SOLICITUD USUARIO)
                # Reglas estrictas:
                # - Venezolano con Cédula: IDVCI
                # - Venezolano con Pasaporte: IDVP
                # - Extranjero con Cédula: IDECI
                # - Extranjero con Pasaporte: IDEP

                doc_type_raw = str(pax.get('documentType', 'CI')).upper()
                nationality_code = nationality.upper()
                id_number_raw = str(pax.get('idNumber', '')).strip()
                
                # 1. Determinar Nacionalidad (V o E)
                # Buscamos 'VE', 'VEN', 'VENEZUELA' o 'V'
                is_venezuelan = any(k == nationality_code for k in ['VE', 'VEN', 'VENEZUELA', 'V'])
                nat_prefix = 'V' if is_venezuelan else 'E'

                # 2. Determinar Tipo de Documento (CI o P)
                # Si contiene 'P', 'PASAPORTE', o el tipo es 'P', es Pasaporte. Sino es Cédula.
                is_passport = doc_type_raw == 'P' or 'PASAPORTE' in doc_type_raw or 'P' in doc_type_raw
                # Forzamos pasaporte si el ID tiene letras y nacionalidad es VE (regla de negocio común, aunque mejor confiar en el tipo)
                if not is_passport and is_venezuelan and any(c.isalpha() for c in id_number_raw):
                    # Si tiene letras y es venezolano, probablemente sea pasaporte mal clasificado, o error.
                    # Pero respetaremos la clasificación de tipo si es explícita.
                    pass

                doc_prefix = 'P' if is_passport else 'CI'

                # 3. Construir el prefijo BASE (VCI, VP, ECI, EP)
                base_prefix = f"{nat_prefix}{doc_prefix}"
                # El prefijo FINAL solicitado es ID + BASE (IDVCI, IDVP, IDECI, IDEP)
                final_prefix = f"ID{base_prefix}"

                # 4. Limpiar el número de documento (Quitar prefijos viejos y basura)
                import re
                
                # Limpieza agresiva: Quitar 'ID', 'VCI', 'VP', 'ECI', 'EP', 'V', 'E', 'CI', 'P' del inicio
                # Normalizamos a mayúsculas
                clean_id = id_number_raw.upper()
                
                # Patrones de prefijos a eliminar del inicio del string
                prefixes_to_remove = ['IDVCI', 'IDVP', 'IDECI', 'IDEP', 'VCI', 'VP', 'ECI', 'EP', 'ID', 'V-', 'E-', 'J-', 'G-']
                
                sorted_prefixes = sorted(prefixes_to_remove, key=len, reverse=True) # Eliminar los más largos primero
                
                for p in sorted_prefixes:
                    if clean_id.startswith(p):
                        clean_id = clean_id[len(p):]
                
                # Segunda limpieza: Quitar caracteres no alfanuméricos
                clean_id = re.sub(r'[^A-Z0-9]', '', clean_id)
                
                # Si es Cédula venezolana, quitar letras también (a veces ponen V123456)
                if not is_passport and is_venezuelan:
                     # Quitar cualquier letra inicial V ó E si quedó
                     if clean_id.startswith('V') or clean_id.startswith('E'):
                         clean_id = clean_id[1:]
                     # Remover cualquier no dígito
                     clean_id = re.sub(r'\D', '', clean_id)

                # 5. Construir ID Final
                final_id_formatted = f"{final_prefix}{clean_id}"
                
                logger.info(f"Fixed Pax ID: Raw='{id_number_raw}' -> Type={doc_prefix} Nat={nat_prefix} -> Prefix='{final_prefix}' -> Clean='{clean_id}' -> Final='{final_id_formatted}'")

                # Mapeo de nacionalidad a 3 letras para TSA (APIS)
                tsa_nationality = "VEN" if is_venezuelan else "USA" # Default a USA si no es VE, pero debería ser dinámico
                if not is_venezuelan:
                    # Intento de mapeo básico si viene algo como 'COL', 'BRA', etc.
                    if len(nationality_code) == 3:
                        tsa_nationality = nationality_code
                    elif len(nationality_code) == 2:
                        # Mapeos comunes
                        mapeo_iso = {'CO': 'COL', 'BR': 'BRA', 'AR': 'ARG', 'CL': 'CHL', 'PA': 'PAN', 'US': 'USA', 'ES': 'ESP'}
                        tsa_nationality = mapeo_iso.get(nationality_code, "USA")

                passenger = {
                    "name": pax['name'].strip().upper(),
                    "lastName": pax['lastName'].strip().upper(),
                    "nationality": nat_prefix, # 'V' o 'E'
                    "idNumber": clean_id, # Enviamos ID limpio para que KIU ponga su prefijo (evita VCIIDVCI...)
                    "documentType": doc_prefix, # 'CI' o 'P'
                    "type": pax['type'],
                    "phoneCode": str(pax.get('phoneCode', '58')),
                    "phone": str(pax['phone']),
                    "email": pax['email'],
                    "birthDate": pax.get('birthDate', '1990-01-01'),
                    "tsa": {
                        "birthDate": pax.get('birthDate', '1990-01-01'),
                        "gender": pax.get('gender', 'M'),
                        "docIssueCountry": tsa_nationality,
                        "birthCountry": tsa_nationality,
                        "tsaDocType": "P" if is_passport else "ID",
                        "tsaDocID": clean_id, 
                        "docExpiry": doc_expiry or "2030-01-01"
                    },
                    # "address": {
                    #     "address": pax.get('address') or 'Av Principal',
                    #     "city": pax.get('city') or 'Caracas',
                    #     "zipCode": pax.get('zipCode') or '1010',
                    #     "state": pax.get('state') or 'Distrito Capital',
                    #     "country": 'Venezuela' if is_venezuelan else 'Otro'
                    # },
                    "departureOccupation": [],
                    "returnOccupation": [],
                    "departureClases": [requested_class],
                    "returnClases": [return_class] if return_class else [],
                    "namePrefix": pax.get('namePrefix', 'MR' if pax.get('gender') == 'M' else 'MRS')
                }
                
                # Pre-llenar occupation arrays en el objeto pasajero (necesario para algunas APIs de KIU)
                # Esto se completará más abajo pero inicializamos estructuras
                passengers_formatted.append(passenger)
            
            # 4. CONSTRUIR OCCUPATION (Soportando múltiples segmentos/escalas)
            # IMPORTANTE: Crear UNA entrada por CADA pasajero individual
            occupation = []
            
            # Segmentos Ida
            ida_segments = departure_flight_data.get('segments', []) if departure_flight_data else []
            
            # Segmentos Vuelta
            vta_segments = return_flight_data.get('segments', []) if return_flight_data else []

            # Recorrer cada pasajero ya formateado para asignarle su ocupación
            for pax in passengers_formatted:
                pax_type = pax.get('type', 'ADT')
                pax_occ = {"type": pax_type, "segments": {}}
                
                # Arrays para el objeto pasajero (algunas aerolíneas lo requieren dentro del Pax)
                dep_occ_list = []
                ret_occ_list = []
                
                # Asignar clase a cada segmento de ida
                for seg in ida_segments:
                    seg_id = seg.get('id')
                    if seg_id:
                        pax_occ["segments"][seg_id] = requested_class
                        dep_occ_list.append({
                            "segmentId": seg_id,
                            "class": requested_class
                        })
                
                # Asignar clase a cada segmento de vuelta
                for seg in vta_segments:
                    seg_id = seg.get('id')
                    if seg_id:
                        pax_occ["segments"][seg_id] = return_class
                        ret_occ_list.append({
                            "segmentId": seg_id,
                            "class": return_class
                        })
                
                # Agregar a la lista global de occupation
                occupation.append(pax_occ)
                
                # Actualizar el objeto pasajero
                pax['departureOccupation'] = dep_occ_list
                pax['returnOccupation'] = ret_occ_list
            
            logger.info(f"Occupation construido: {len(occupation)} entradas para {len(passengers_formatted)} pasajeros")
            logger.debug(f"Occupation: {occupation}")

            # VALIDACIÓN CRÍTICA: Asegurar que occupation tiene segmentos
            has_segments = False
            for occ in occupation:
                if occ.get('segments') and len(occ.get('segments')) > 0:
                    has_segments = True
                    break
            
            if not has_segments:
                logger.error("❌ CRÍTICO: Occupation generado no tiene segmentos. Abortando para evitar PNR fantasma.")
                logger.error(f"IDA Segments IDs: {[s.get('id') for s in ida_segments]}")
                if return_flight_option:
                    logger.error(f"VUELTA Segments IDs: {[s.get('id') for s in vta_segments]}")
                return {
                    "success": False,
                    "error": "Error técnico: No se pudieron asignar los segmentos de vuelo. Por favor intenta buscar el vuelo nuevamente."
                }

            
            # 5. CREAR RESERVACIÓN CON REINTENTOS
            logger.info(f"Enviando solicitud de reserva a KIU (Ida: {flight_number}, Vuelta: {r_flight_number if return_flight_option else 'N/A'})")
            
            # Intentar hasta 3 veces en caso de timeout o expiración
            max_attempts = 3
            result = None
            
            for attempt in range(1, max_attempts + 1):
                logger.info(f"Intento {attempt}/{max_attempts} de crear reserva...")
                
                # VALIDAR OCCUPATION (Incluso tras refresh)
                has_segments_chk = False
                for occ in occupation:
                    if occ.get('segments') and len(occ.get('segments')) > 0:
                        has_segments_chk = True
                        break
                
                if not has_segments_chk:
                    logger.error(f"❌ CRÍTICO (Intento {attempt}): Occupation sin segmentos. Deteniendo.")
                    result = {"success": False, "error": "Error interno: Pérdida de segmentos de vuelo."}
                    break
                
                result = self.kiu.create_booking(
                    departure_flight=departure_flight_data,
                    passengers=passengers_formatted,
                    occupation=occupation,
                    return_flight=return_flight_data,
                    observations="",
                    user_phone=user_phone
                    # ticket_time_limit removido para evitar conflictos con reglas tarifarias
                )
                
                # Si fue exitoso, salir del loop
                if result.get('success'):
                    logger.info(f"Reserva creada exitosamente en intento {attempt}")
                    break
                
                error_msg = result.get('error', '').lower()
                
                # Si fue timeout y no es el último intento, esperar y reintentar
                if result.get('timeout') and attempt < max_attempts:
                    logger.warning(f"Timeout en intento {attempt}, esperando 3 segundos antes de reintentar...")
                    import time
                    time.sleep(3)
                    continue
                
                # Si es error de expiración y no es el último intento, refrescar datos y reintentar
                expiration_keywords = ['time limit', 'timelimit', 'expired', 'expirado', 'expir', 'caducado', 'session expired']
                is_expiration = any(kw in error_msg for kw in expiration_keywords)
                
                if is_expiration and attempt < max_attempts:
                    logger.warning(f"Datos expirados en intento {attempt}, refrescando vuelos...")
                    import time
                    time.sleep(1)
                    
                    # Refrescar datos del vuelo de ida
                    fresh_ida = self.search_flights(origin, destination, date, passengers)
                    found_ida = False
                    for f in fresh_ida:
                        if f.get('flight_number') == flight_number and (not requested_airline or f.get('airline') == requested_airline):
                            departure_flight_data = f.get('api_data')
                            found_ida = True
                            
                            # Actualizar occupation con nuevo segment_id
                            ida_segments = departure_flight_data.get('segments', [])
                            occupation = []
                            for pax_type, count in passengers.items():
                                if count > 0:
                                    for i in range(count):
                                        pax_occ = {"type": pax_type, "segments": {}}
                                        for seg in ida_segments:
                                            seg_id = seg.get('id')
                                            if seg_id:
                                                pax_occ["segments"][seg_id] = requested_class
                                        occupation.append(pax_occ)
                            logger.info(f"Datos de ida refrescados.")
                            
                            # Refrescar datos de VUELTA si existe
                            if return_flight_option:
                                logger.info(f"Refrescando datos de vuelta por expiración...")
                                r_origin = return_flight_option.get('origin')
                                r_destination = return_flight_option.get('destination')
                                r_date = return_flight_option.get('date')
                                r_flight_number = return_flight_option.get('flight_number')
                                r_airline = return_flight_option.get('airline')
                                return_class = return_flight_option.get('class', 'Y')

                                fresh_vuelta = self.search_flights(r_origin, r_destination, r_date, passengers)
                                found_vuelta = False
                                for f in fresh_vuelta:
                                    if f.get('flight_number') == r_flight_number and (not r_airline or f.get('airline') == r_airline):
                                        return_flight_data = f.get('api_data')
                                        found_vuelta = True
                                        
                                        # Actualizar occupation de vuelta
                                        vuelta_segments = return_flight_data.get('segments', [])
                                        # Mantener occupation existente y añadir nuevos segmentos
                                        # Nota: occupation es una lista [pax1, pax2]. Cada pax tiene {type, segments}
                                        # Necesitamos actualizar el diccionario 'segments' de cada pax
                                        
                                        # Reconstruir occupation completo para estar seguros
                                        new_occupation = []
                                        
                                        # Segmentos de IDA (ya actualizados en departure_flight_data)
                                        ida_segments = departure_flight_data.get('segments', [])
                                        
                                        for pax_type, count in passengers.items():
                                            if count > 0:
                                                for i in range(count):
                                                    pax_occ = {"type": pax_type, "segments": {}}
                                                    
                                                    # Agregar segmentos de IDA
                                                    for seg in ida_segments:
                                                        if seg.get('id'):
                                                            pax_occ["segments"][seg.get('id')] = requested_class
                                                    
                                                    # Agregar segmentos de VUELTA
                                                    for seg in vuelta_segments:
                                                        if seg.get('id'):
                                                            pax_occ["segments"][seg.get('id')] = return_class
                                                            
                                                    new_occupation.append(pax_occ)
                                        
                                        occupation = new_occupation
                                        logger.info(f"Datos de vuelta refrescados.")
                                        break
                                        
                            logger.info(f"Reintentando reserva con datos frescos...")
                            break # Salir del loop de búsqueda de ida (ya encontramos la ida)
                    
                    if not found_ida:
                         logger.error(f"❌ Vuelo de ida NO encontrado en refresh: {flight_number}")
                         result = {"success": False, "error": f"El vuelo {flight_number} ya no está disponible o cambió de precio. Por favor busca de nuevo."}
                         break # Salir del loop de intentos (NO reintentar)

                    if return_flight_option and not found_vuelta:
                         logger.error(f"❌ Vuelo de vuelta NO encontrado en refresh")
                         result = {"success": False, "error": f"El vuelo de vuelta ya no está disponible. Por favor busca de nuevo."}
                         break # Salir del loop de intentos
                    continue
                
                # Si es otro tipo de error, no reintentar
                if not result.get('timeout'):
                    logger.error(f"Error no-recuperable en intento {attempt}: {result.get('error')}")
                    break
            
            if result.get('success'):
                data = result.get('data', {})
                vid = data.get('vid')
                sesion_json = data.get('sesion_json', {})
                
                pnr = None
                actual_price = None
                if 'vuelo' in sesion_json and len(sesion_json['vuelo']) > 0:
                    vuelo_data = sesion_json['vuelo'][0]
                    pnr = vuelo_data.get('loc')
                    # Extraer precio real de la respuesta de KIU si está disponible
                    actual_price = vuelo_data.get('precio') or vuelo_data.get('total')
                    if isinstance(actual_price, list) and len(actual_price) > 0:
                        actual_price = actual_price[0]
                
                # Construir mensaje de éxito con ruta
                ruta_str = f"{origin}-{destination}"
                if return_flight_option:
                    ruta_str += f" / {return_flight_option.get('origin')}-{return_flight_option.get('destination')}"

                return {
                    "success": True,
                    "pnr": pnr,
                    "vid": vid,
                    "actual_price": actual_price,
                    "message": f"✅ Reserva creada exitosamente!\n🎫 PNR: {pnr}\n📍 Ruta: {ruta_str}\n📋 ID: {vid}"
                }
            else:
                error_msg = result.get('error', 'Error al crear reserva')
                error_lower = error_msg.lower()
                logger.error(f"Error en create_booking - Mensaje completo: {error_msg}")
                
                # Detectar errores específicos y dar mensajes claros
                if 'wait list closed' in error_lower or 'waitlist closed' in error_lower:
                    return {
                        "success": False,
                        "error": "Lo siento, la clase seleccionada ya no tiene asientos disponibles. Por favor selecciona otra clase o busca otro vuelo.",
                        "error_type": "no_availability"
                    }
                
                if result.get('timeout'):
                    return {
                        "success": False,
                        "error": "Timeout: La aerolínea tardó mucho en responder.",
                        "timeout": True
                    }
                
                # Mostrar el error real de la API
                return {
                    "success": False,
                    "error": error_msg
                }
                
        except Exception as e:
            logger.error(f"Error creating single booking: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_booking_details(self, pnr: str = None, vid: int = None) -> Dict:
        """Consulta reservación de la API - busca el PNR específico con reintentos"""
        try:
            if not pnr:
                return {"success": False, "error": "PNR requerido"}
            
            pnr_upper = pnr.upper()
            logger.info(f"Obteniendo detalles del PNR: {pnr_upper} (Estrategia Mejorada con Reintentos)")
            
            status_result = None
            purchase_result = None
            status_error = None
            
            # ESTRATEGIA 1: Intentar get_booking_status con MÚLTIPLES REINTENTOS
            max_status_retries = 3
            for attempt in range(1, max_status_retries + 1):
                try:
                    logger.info(f"Intento {attempt}/{max_status_retries} - Consultando status PNR: {pnr_upper}")
                    status_result = self.kiu.get_booking_status(pnr_upper)
                    
                    if status_result and status_result.get('success'):
                        logger.info(f"✅ Status PNR obtenido exitosamente en intento {attempt}")
                        break
                    else:
                        logger.warning(f"Intento {attempt} falló: {status_result.get('error') if status_result else 'No response'}")
                        if attempt < max_status_retries:
                            import time
                            time.sleep(2)  # Esperar 2 segundos antes de reintentar
                except Exception as e:
                    status_error = str(e)
                    logger.warning(f"Intento {attempt} - Error status PNR: {e}")
                    if attempt < max_status_retries:
                        import time
                        time.sleep(2)
            
            # ESTRATEGIA 2: Intentar get_purchase_data en paralelo (solo si status falló)
            if not status_result or not status_result.get('success'):
                try:
                    logger.info(f"Status falló, intentando purchases para PNR: {pnr_upper}")
                    purchase_result = self.kiu.get_purchase_data(pnr=pnr_upper)
                except Exception as e:
                    logger.warning(f"Error purchase PNR: {e}")

            # ESTRATEGIA 1: Usar Status
            if status_result and status_result.get('success'):
                data = status_result.get('data', {})
                loc_data = data.get('loc', {})
                
                # IMPORTANTE: La API puede retornar 'localizador' como array o como objeto
                # Si es array, tomar el primer elemento
                if isinstance(data.get('localizador'), list) and len(data.get('localizador')) > 0:
                    loc_data = data.get('localizador')[0]
                elif 'loc' in data:
                    loc_data = data.get('loc', {})
                
                # Validar PNR (más flexible - acepta si el PNR está contenido o es similar)
                localizador_api = loc_data.get('localizador', '').upper()
                if loc_data and (localizador_api == pnr_upper or pnr_upper in localizador_api or localizador_api in pnr_upper):
                    logger.info(f"PNR {pnr_upper} encontrado vía Status API")
                    
                    # Extraer pasajeros - puede estar en 'pasajeros' o en loc_data['pasajeros']
                    pasajeros = data.get('pasajeros', []) or loc_data.get('pasajeros', [])
                    
                    flight_info = []
                    # ESTRATEGIA MEJORADA: Buscar vuelos en múltiples ubicaciones
                    vuelos = data.get('vuelos', [])
                    
                    # Si no hay vuelos, intentar extraer de loc_data
                    if not vuelos:
                        vuelos = loc_data.get('vuelos', [])
                    
                    # Si aún no hay vuelos, construir desde la ruta
                    if not vuelos and loc_data.get('ruta'):
                        logger.info("Construyendo vuelo desde ruta básica")
                        # Crear un vuelo básico con la información disponible
                        ruta = loc_data.get('ruta', '')
                        parts = ruta.split('-') if '-' in ruta else []
                        if len(parts) >= 2:
                            flight_info.append({
                                "aerolinea": "N/A",
                                "vuelo": "N/A",
                                "ruta": ruta,
                                "fecha": "N/A",
                                "hora_salida": "N/A",
                                "hora_llegada": "N/A",
                                "clase": "N/A",
                                "estado": estado_texto
                            })
                    else:
                        # Procesar vuelos normalmente
                        for v in vuelos:
                            segs = v.get('segmentos', [])
                            for seg in segs:
                                airline_name = seg.get('st_aerolinea', seg.get('aerolinea', ''))
                                flight_number = seg.get('vuelo', '')
                                flight_status = seg.get('estado', 'N/A')
                                departure_time = seg.get('horasalida', '')[:5] if seg.get('horasalida') else ''
                                arrival_time = seg.get('horallegada', '')[:5] if seg.get('horallegada') else ''
                                
                                flight_info.append({
                                    "aerolinea": airline_name,
                                    "vuelo": flight_number,
                                    "ruta": f"{seg.get('partida', '')}-{seg.get('destino', '')}",
                                    "fecha": seg.get('diasalida', ''),
                                    "hora_salida": departure_time,
                                    "hora_llegada": arrival_time,
                                    "clase": seg.get('clase', ''),
                                    "estado": flight_status,
                                    "asiento": seg.get('asiento', seg.get('seat', '')),
                                    "equipaje": seg.get('equipaje', seg.get('baggage', '')),
                                    "cabina": seg.get('cabina', seg.get('cabin', ''))
                                })
                    
                    # Estado texto
                    estado_num = loc_data.get('estado', '')
                    estado_texto = str(estado_num)
                    status_map = {
                        "0": "Cancelado", "1": "Pendiente", "2": "Confirmado",
                        "3": "Emitido", "4": "Pagado", "5": "Expirado",
                        "6": "Reembolsado", "7": "En proceso", "8": "Completado"
                    }
                    if estado_texto in status_map:
                        estado_texto = status_map[estado_texto]
                    
                    # Vencimiento (Priorizar ticketTimeLimit si existe, sino vencimiento)
                    vencimiento = loc_data.get('ticketTimeLimit') or loc_data.get('vencimiento', '')
                    
                    if vencimiento:
                        try:
                            from datetime import datetime, date
                            # Limpiar formato ISO
                            vencimiento_clean = vencimiento.replace('T', ' ').split('.')[0]
                            venc_dt = datetime.fromisoformat(vencimiento_clean)
                            
                            # Formato DD/MM/YYYY HH:MM
                            vencimiento_str = venc_dt.strftime('%d/%m/%Y %H:%M')
                            
                            # Si es hoy, agregar aclaratoria
                            if venc_dt.date() == date.today():
                                vencimiento = f"{vencimiento_str} (Hoy)"
                            else:
                                vencimiento = vencimiento_str
                        except:
                            # Si falla el parseo, devolver string original
                            pass
                    
                    return {
                        "success": True,
                        "pnr": loc_data.get('localizador', pnr),
                        "vid": loc_data.get('vid', ''),
                        "status": estado_texto,
                        "flight_status": status_result.get('data', {}).get('vuelos', [{}])[0].get('segmentos', [{}])[0].get('estado', 'N/A'),
                        "client": (pasajeros[0].get('nombre', '') + ' ' + pasajeros[0].get('apellido', '')).strip() if pasajeros else 'N/A',
                        "passengers": [
                            {
                                "nombre": (p.get('nombre', '') + ' ' + p.get('apellido', '')).strip(),
                                "tipo": p.get('tipo', 'ADT'),
                                "documento": (lambda d: d[3:] if d.startswith('VCIIDVCI') else 
                                               d[2:] if d.startswith('VPIDVP') else
                                               d[3:] if d.startswith('ECIIDECI') else
                                               d[2:] if d.startswith('EPIDEP') else d)(p.get('documento', '')),
                                "telefono": p.get('telefono', '').replace('MIA ', '').replace('NET ', '')
                            } for p in pasajeros
                        ],
                        "flights": flight_info,
                        "route": loc_data.get('ruta', 'N/A'),
                        "balance": f"${loc_data.get('precio', 'N/A')} USD",
                        "base": loc_data.get('base', ''),
                        "vencimiento": vencimiento,
                        "type": "vuelos"
                    }

            # ESTRATEGIA 2: Fallback a Purchases
            logger.info(f"Fallback a Purchases para {pnr_upper}")
            if purchase_result and purchase_result.get('success'):
                data = purchase_result.get('data', {})
                purchases = data.get('data', [])
                
                for purchase in purchases:
                    criterion = purchase.get('criterion', {})
                    loc = criterion.get('loc', '')
                    
                    if loc:
                        loc_clean = loc.replace('Loc:', '').replace('loc:', '').strip().upper()
                        if loc_clean == pnr_upper:
                            logger.info(f"PNR {pnr_upper} encontrado en purchases")
                            
                            desglose = purchase.get('desglose', {})
                            servicios = desglose.get('servicios', [])
                            details = purchase.get('details', {})
                            
                            flight_info = []
                            for servicio in servicios:
                                if 'Vuelo' in servicio:
                                    flight_info.append({
                                        "vuelo": servicio.get('Vuelo', ''),
                                        "ruta": servicio.get('Servicio', ''),
                                        "fecha": servicio.get('Fecha', ''),
                                        "hora_salida": servicio.get('Salida', ''),
                                        "hora_llegada": servicio.get('Llegada', ''),
                                        "precio": servicio.get('Total', '')
                                    })
                            
                            return {
                                "success": True,
                                "pnr": pnr_upper,
                                "status": purchase.get('status', 'N/A'),
                                "client": purchase.get('cliente', 'N/A'),
                                "flights": flight_info,
                                "route": details.get('details', 'N/A'),
                                "balance": purchase.get('balance', 'N/A'),
                                "type": purchase.get('type', 'vuelos'),
                                "passengers": [] # Purchases a veces no trae detalle de pax estructurado aquí
                            }

            # FINAL: No encontrado en ninguna estrategia
            logger.error(f"❌ PNR {pnr_upper} NO ENCONTRADO después de todas las estrategias")
            logger.error(f"Status result: {status_result}")
            logger.error(f"Purchase result: {purchase_result}")
            
            error_msg = f"No se encontró la reserva con PNR {pnr_upper}.\n\n"
            error_msg += "Posibles causas:\n"
            error_msg += "• El código PNR es incorrecto\n"
            error_msg += "• La reserva fue cancelada\n"
            error_msg += "• La reserva aún no está sincronizada en el sistema\n\n"
            error_msg += "Por favor verifica el código e intenta nuevamente."
            
            if status_error:
                error_msg += f"\n\nError técnico: {status_error}"
            
            return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"Error en get_booking_details: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error al consultar reserva: {str(e)}"}
    
    def _normalize_date(self, date_str: str) -> str:
        """Normaliza fecha a YYYY-MM-DD"""
        try:
            formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]
            for fmt in formats:
                try:
                    date_obj = datetime.strptime(date_str, fmt)
                    return date_obj.strftime("%Y-%m-%d")
                except:
                    continue
            return date_str
        except:
            return date_str


# Instancia global
flight_service = FlightBookingServiceComplete()

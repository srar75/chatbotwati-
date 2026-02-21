#!/usr/bin/env python3
"""
Script para aplicar todos los patches al gemini_agent_bot.py
Ejecuta: python APPLY_PATCHES.py

Este script modifica gemini_agent_bot.py directamente con todas las correcciones.
"""

import re

def apply_patches():
    with open('gemini_agent_bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    patches_applied = []

    # =========================================================================
    # PATCH #1: handle_message - Agregar claves faltantes en keys_to_clear
    # =========================================================================
    old = """                keys_to_clear = [
                    'awaiting_flight_confirmation', 'flight_selection_fully_confirmed', 
                    'waiting_for_field', 'passengers_list', 'extracted_data', 
                    'selected_flight', 'selected_flight_index', 'flight_confirmed',
                    'num_passengers', 'num_adults', 'num_children', 'num_infants',
                    'available_flights', 'return_flights', 'pending_flight_index',
                    'ida_class_confirmed', 'return_date', 'is_round_trip',
                    'pending_return_flight_index', 'selected_return_flight',
                    'selected_return_flight_index', 'selected_flight_class',
                    'selected_return_flight_class', 'return_flight_confirmed',
                    'using_document_image', 'document_image_url',
                    'ida_flight_index', 'ida_flight_class', 'ida_flight_classes_prices',
                    'return_flight_fully_confirmed', 'flight_classes_prices',
                    'return_flight_classes_prices', 'waiting_for_cedula_image'
                ]"""
    new = """                keys_to_clear = [
                    'awaiting_flight_confirmation', 'flight_selection_fully_confirmed', 
                    'waiting_for_field', 'passengers_list', 'extracted_data', 
                    'selected_flight', 'selected_flight_index', 'flight_confirmed',
                    'num_passengers', 'num_adults', 'num_children', 'num_infants',
                    'available_flights', 'return_flights', 'pending_flight_index',
                    'ida_class_confirmed', 'return_date', 'is_round_trip',
                    'pending_return_flight_index', 'selected_return_flight',
                    'selected_return_flight_index', 'selected_flight_class',
                    'selected_return_flight_class', 'return_flight_confirmed',
                    'using_document_image', 'document_image_url',
                    'ida_flight_index', 'ida_flight_class', 'ida_flight_classes_prices',
                    'return_flight_fully_confirmed', 'flight_classes_prices',
                    'return_flight_classes_prices', 'waiting_for_cedula_image',
                    # FIX #1: Agregar claves faltantes que causaban estado sucio entre sesiones
                    'awaiting_class_selection', 'awaiting_class_selection_is_return',
                    'search_results', 'ai_history',
                ]"""
    if old in content:
        content = content.replace(old, new)
        patches_applied.append('PATCH #1: keys_to_clear actualizado')
    else:
        print('WARN: PATCH #1 no encontrado, puede ya estar aplicado o el formato cambio')

    # =========================================================================
    # PATCH #2: awaiting_class_selection - Guardar backup ANTES de limpiar estado
    # =========================================================================
    old2 = """                if extracted_class and len(extracted_class) == 1:
                    is_return = session.data.get('awaiting_class_selection_is_return', False)
                    flight_index = session.data.get('selected_return_flight_index' if is_return else 'pending_flight_index') or session.data.get('selected_flight_index', 1)
                    
                    logger.info(f"=== CLASE SELECCIONADA: {extracted_class} (is_return={is_return}, flight_index={flight_index}) ===")
                    self._send_response(phone, "Preparando confirmaci\u00f3n de vuelo...", session)
                    
                    # Limpiar el estado de espera de clase
                    session.data['awaiting_class_selection'] = False
                    
                    # Llamar a la funci\u00f3n de confirmaci\u00f3n con la clase elegida
                    result = self._confirm_flight_selection_function(
                        flight_index=flight_index,
                        flight_class=extracted_class,
                        session=session,
                        is_return=is_return
                    )
                    
                    if result.get('success'):
                        # Guardar la clase seleccionada en sesi\u00f3n
                        if is_return:
                            session.data['selected_return_flight_class'] = extracted_class
                        else:
                            session.data['selected_flight_class'] = extracted_class
                        # Mostrar el mensaje de confirmaci\u00f3n del vuelo
                        return self._send_response(phone, result.get('message', ''), session)
                    else:
                        # Error - posiblemente clase no disponible
                        # Restaurar estado de selecci\u00f3n
                        session.data['awaiting_class_selection'] = True
                        return self._send_response(phone, result.get('message', 'Clase no disponible. Por favor elige otra letra.'), session)"""
    new2 = """                if extracted_class and len(extracted_class) == 1:
                    is_return = session.data.get('awaiting_class_selection_is_return', False)
                    flight_index = session.data.get('selected_return_flight_index' if is_return else 'pending_flight_index') or session.data.get('selected_flight_index', 1)
                    
                    logger.info(f"=== CLASE SELECCIONADA: {extracted_class} (is_return={is_return}, flight_index={flight_index}) ===")
                    self._send_response(phone, "Preparando confirmaci\u00f3n de vuelo...", session)
                    
                    # FIX #2: Guardar backup del indice ANTES de limpiar el estado
                    # para poder restaurarlo si la clase no est\u00e1 disponible
                    backup_flight_index = flight_index
                    backup_is_return = is_return
                    
                    # FIX #8: Guardar la clase en sesi\u00f3n ANTES de llamar a la funci\u00f3n
                    # (la funcion internamente puede necesitarla)
                    if is_return:
                        session.data['selected_return_flight_class'] = extracted_class
                    else:
                        session.data['selected_flight_class'] = extracted_class
                    
                    # Limpiar el estado de espera de clase
                    session.data['awaiting_class_selection'] = False
                    
                    # Llamar a la funci\u00f3n de confirmaci\u00f3n con la clase elegida
                    result = self._confirm_flight_selection_function(
                        flight_index=flight_index,
                        flight_class=extracted_class,
                        session=session,
                        is_return=is_return
                    )
                    
                    if result.get('success'):
                        # Mostrar el mensaje de confirmaci\u00f3n del vuelo
                        return self._send_response(phone, result.get('message', ''), session)
                    else:
                        # FIX #2+3: Error - restaurar estado correctamente incluyendo el indice
                        session.data['awaiting_class_selection'] = True
                        session.data['awaiting_class_selection_is_return'] = backup_is_return
                        if backup_is_return:
                            if not session.data.get('selected_return_flight_index'):
                                session.data['selected_return_flight_index'] = backup_flight_index
                        else:
                            session.data['pending_flight_index'] = backup_flight_index
                        # Limpiar clase guardada prematuramente
                        if is_return:
                            session.data.pop('selected_return_flight_class', None)
                        else:
                            session.data.pop('selected_flight_class', None)
                        return self._send_response(phone, result.get('message', 'Clase no disponible. Por favor elige otra letra.'), session)"""
    if old2 in content:
        content = content.replace(old2, new2)
        patches_applied.append('PATCH #2+3+8: awaiting_class_selection corregido')
    else:
        print('WARN: PATCH #2 no encontrado')

    # =========================================================================
    # PATCH #4: _handle_function_call search_flights - Validar datos obligatorios
    # =========================================================================
    old4 = """            if function_name == "search_flights":
                # Enviar mensaje de "buscando" ANTES de ejecutar la b\u00fasqueda
                origin = function_args.get('origin')
                destination = function_args.get('destination')
                date = function_args.get('date')
                trip_type = function_args.get('trip_type', 'ida')
                # Nuevos campos detallados - Conversi\u00f3n segura de tipos
                safe_int = lambda x, default: int(float(x)) if x is not None and str(x).replace('.', '', 1).isdigit() else default
                
                # Asegurar que num_passengers tenga un valor v\u00e1lido
                raw_num_passengers = function_args.get('num_passengers')
                num_passengers = safe_int(raw_num_passengers, 1)"""
    new4 = """            if function_name == "search_flights":
                # Enviar mensaje de "buscando" ANTES de ejecutar la b\u00fasqueda
                origin = function_args.get('origin')
                destination = function_args.get('destination')
                date = function_args.get('date')
                trip_type = function_args.get('trip_type', 'ida')
                
                # FIX #4: Validar datos obligatorios antes de proceder
                missing_data = []
                if not origin or len(str(origin).strip()) < 2:
                    missing_data.append('ciudad de origen')
                if not destination or len(str(destination).strip()) < 2:
                    missing_data.append('ciudad de destino')
                if not date or len(str(date).strip()) < 8:
                    missing_data.append('fecha de viaje')
                if missing_data:
                    logger.warning(f"search_flights llamado sin datos obligatorios: {missing_data}")
                    return self._send_response(phone,
                        f"Necesito {', '.join(missing_data)} para buscar vuelos. \u00bfMe lo puedes indicar?",
                        session
                    )
                
                # Nuevos campos detallados - Conversi\u00f3n segura de tipos
                safe_int = lambda x, default: int(float(x)) if x is not None and str(x).replace('.', '', 1).isdigit() else default
                
                # Asegurar que num_passengers tenga un valor v\u00e1lido
                raw_num_passengers = function_args.get('num_passengers')
                num_passengers = safe_int(raw_num_passengers, 0)
                
                # FIX #4b: Si num_passengers es 0 o negativo, pedir al usuario
                if num_passengers < 1:
                    logger.warning(f"search_flights llamado sin num_passengers v\u00e1lido: {raw_num_passengers}")
                    return self._send_response(phone,
                        "\u00bfPara cu\u00e1ntas personas necesitas el vuelo?",
                        session
                    )"""
    if old4 in content:
        content = content.replace(old4, new4)
        patches_applied.append('PATCH #4: Validacion de datos obligatorios en search_flights')
    else:
        print('WARN: PATCH #4 no encontrado')

    # =========================================================================
    # PATCH #5: search_flights - No limpiar datos de IDA al buscar VUELTA
    # =========================================================================
    old5 = """                # RESET DE ESTADOS DE CONFIRMARCI\u00d3N PARA NUEVA B\u00daSSQUEDA
                if trip_type == 'ida':
                    session.data['flight_confirmed'] = False
                    session.data['return_flight_confirmed'] = False
                    session.data['ida_class_confirmed'] = False
                    session.data['flight_selection_fully_confirmed'] = False
                    session.data['awaiting_flight_confirmation'] = False
                    session.data.pop('selected_flight_index', None)
                    session.data.pop('selected_flight_class', None)
                    session.data.pop('selected_return_flight_index', None)
                    session.data.pop('selected_return_flight_class', None)
                    session.data.pop('pending_flight_index', None)
                    session.data.pop('pending_return_flight_index', None)
                    session.data.pop('flight_classes_prices', None)
                    session.data.pop('return_flight_classes_prices', None)
                    session.data.pop('ida_flight_classes_prices', None)
                    session.data.pop('available_flights', None)
                    session.data.pop('return_flights', None)
                    session.data.pop('search_results', None)
                    session.data.pop('ida_flight_index', None)
                    session.data.pop('ida_flight_class', None)"""
    new5 = """                # FIX #5: RESET DE ESTADOS DE CONFIRMACI\u00d3N PARA NUEVA B\u00daSSQUEDA
                # SOLO resetear en trip_type=='ida' (nueva busqueda). Para 'vuelta', preservar datos de ida.
                if trip_type == 'vuelta':
                    # Para b\u00fasqueda de vuelta: solo limpiar estados de selecci\u00f3n de vuelta
                    session.data.pop('selected_return_flight_index', None)
                    session.data.pop('selected_return_flight_class', None)
                    session.data.pop('pending_return_flight_index', None)
                    session.data.pop('return_flight_classes_prices', None)
                    session.data.pop('return_flights', None)
                    session.data['return_flight_confirmed'] = False
                    session.data['return_flight_fully_confirmed'] = False
                    logger.info("B\u00fasqueda de VUELTA: preservando datos de IDA en sesi\u00f3n")
                elif trip_type == 'ida':
                    session.data['flight_confirmed'] = False
                    session.data['return_flight_confirmed'] = False
                    session.data['ida_class_confirmed'] = False
                    session.data['flight_selection_fully_confirmed'] = False
                    session.data['awaiting_flight_confirmation'] = False
                    session.data['awaiting_class_selection'] = False
                    session.data.pop('selected_flight_index', None)
                    session.data.pop('selected_flight_class', None)
                    session.data.pop('selected_return_flight_index', None)
                    session.data.pop('selected_return_flight_class', None)
                    session.data.pop('pending_flight_index', None)
                    session.data.pop('pending_return_flight_index', None)
                    session.data.pop('flight_classes_prices', None)
                    session.data.pop('return_flight_classes_prices', None)
                    session.data.pop('ida_flight_classes_prices', None)
                    session.data.pop('available_flights', None)
                    session.data.pop('return_flights', None)
                    session.data.pop('search_results', None)
                    session.data.pop('ida_flight_index', None)
                    session.data.pop('ida_flight_class', None)"""
    if old5 in content:
        content = content.replace(old5, new5)
        patches_applied.append('PATCH #5: No limpiar datos de IDA al buscar VUELTA')
    else:
        print('WARN: PATCH #5 no encontrado')

    # =========================================================================
    # PATCH #6: return_date - Siempre actualizar desde function_args
    # =========================================================================
    old6 = """                # Guardar return_date si existe
                if function_args.get('return_date'):
                    session.data['return_date'] = function_args.get('return_date')"""
    new6 = """                # FIX #6: Guardar return_date siempre que venga en los args (actualizar si cambi\u00f3)
                new_return_date = function_args.get('return_date')
                if new_return_date:
                    old_date = session.data.get('return_date')
                    if old_date and old_date != new_return_date:
                        logger.info(f"Actualizando return_date: {old_date} -> {new_return_date}")
                    session.data['return_date'] = new_return_date"""
    if old6 in content:
        content = content.replace(old6, new6)
        patches_applied.append('PATCH #6: return_date siempre se actualiza')
    else:
        print('WARN: PATCH #6 no encontrado')

    # =========================================================================
    # PATCH #2b: manual - Limpiar awaiting_flight_confirmation al iniciar flujo manual
    # =========================================================================
    old_manual = """                if current_count < total_passengers:
                    # Empezar a pedir datos comenzando por el Nombre
                    session.data['waiting_for_field'] = 'nombre'
                    passenger_label = f" (Pasajero {current_count + 1} de {total_passengers})" if total_passengers > 1 else ""
                    return self._send_response(phone, f"Entendido, ingreso manual. \u00bfCu\u00e1l es el *nombre* (sin apellidos) del pasajero?{passenger_label}", session)"""
    new_manual = """                if current_count < total_passengers:
                    # Empezar a pedir datos comenzando por el Nombre
                    session.data['waiting_for_field'] = 'nombre'
                    # FIX #2b: Limpiar awaiting_flight_confirmation para que el flujo de pasajero
                    # no sea interceptado por el bloque de confirmaci\u00f3n de vuelo
                    session.data['awaiting_flight_confirmation'] = False
                    passenger_label = f" (Pasajero {current_count + 1} de {total_passengers})" if total_passengers > 1 else ""
                    return self._send_response(phone, f"Entendido, ingreso manual. \u00bfCu\u00e1l es el *nombre* (sin apellidos) del pasajero?{passenger_label}", session)"""
    if old_manual in content:
        content = content.replace(old_manual, new_manual)
        patches_applied.append('PATCH #2b: Limpieza de awaiting_flight_confirmation en flujo manual')
    else:
        print('WARN: PATCH #2b no encontrado')

    # =========================================================================
    # PATCH #7: round-trip - Evitar doble mensaje al confirmar clase de IDA y buscar vuelta
    # Reemplazar el mensaje de instruccion interna por una llamada directa en Python
    # =========================================================================
    old7 = """                                # Modificar el mensaje para que la AI procese la b\u00fasqueda autom\u00e1ticamente
                                # FUNDAMENTAL: NO generar otro mensaje de confirmaci\u00f3n (ya se envi\u00f3 confirm_msg arriba)
                                # Solo pedir a Gemini que llame a search_flights para el vuelo de vuelta
                                message = f"INSTRUCCION INTERNA - NO MOSTRAR AL USUARIO: Busca ahora el vuelo de REGRESO origen={ida_flight.get('destination','CCS')} destino={ida_flight.get('origin','CCS')} fecha={return_date} trip_type=vuelta. NO confirmes nada previamente, NO repitas informaci\u00f3n del vuelo de ida. Solo llama a la funci\u00f3n de b\u00fasqueda y muestra los resultados."
                                
                                # No retornamos, para que el c\u00f3digo fluya hacia la llamada a Gemini al final de _process_with_ai
                                logger.info("Instrucci\u00f3n de b\u00fasqueda de regreso preparada para Gemini")"""
    new7 = """                                # FIX #7: Llamar directamente a _search_flights_function para el vuelo de vuelta
                                # Esto evita el doble mensaje que ocurria cuando Gemini generaba texto adicional
                                logger.info(f"Buscando vuelo de regreso directo: {ida_flight.get('destination','CCS')} -> {ida_flight.get('origin','CCS')} para {return_date}")
                                
                                # Obtener desglose de pasajeros de la sesi\u00f3n
                                adults_rt = session.data.get('num_adults', session.data.get('num_passengers', 1))
                                children_rt = session.data.get('num_children', 0)
                                infants_rt = session.data.get('num_infants', 0)
                                
                                result_vuelta = self._search_flights_function(
                                    origin=ida_flight.get('destination', 'CCS'),
                                    destination=ida_flight.get('origin', 'CCS'),
                                    date=return_date,
                                    session=session,
                                    trip_type='vuelta',
                                    adults=adults_rt,
                                    children=children_rt,
                                    infants=infants_rt
                                )
                                
                                if result_vuelta.get('success') and result_vuelta.get('message'):
                                    # Agregar resultado al historial para que Gemini tenga contexto
                                    history = session.data.get('ai_history', [])
                                    history.append({"role": "user", "parts": [{"text": f"[Sistema] Vuelos de regreso obtenidos"}]})
                                    history.append({"role": "model", "parts": [{"text": result_vuelta.get('message')}]})
                                    session.data['ai_history'] = history
                                    return self._send_response(phone, result_vuelta.get('message'), session)
                                elif not result_vuelta.get('success'):
                                    return self._send_response(phone,
                                        f"No encontr\u00e9 vuelos de regreso disponibles para el {format_date_dd_mm_yyyy(return_date)}. \u00bfDeseas intentar con otra fecha?",
                                        session
                                    )
                                # Si ya se envi\u00f3 el mensaje de vuelta, retornar
                                return None"""
    if old7 in content:
        content = content.replace(old7, new7)
        patches_applied.append('PATCH #7: Llamada directa a search_flights para vuelta (sin Gemini intermediario)')
    else:
        print('WARN: PATCH #7 no encontrado')

    # =========================================================================
    # PATCH #9: Agregar guard defensivo en _send_booking_success_message
    # =========================================================================
    # Este patch no puede aplicarse via string replace facilmente sin ver la funcion completa.
    # Se documenta aqui como recordatorio.
    print('NOTE: PATCH #9 (_send_booking_success_message guards) requiere revision manual')

    # =========================================================================
    # Guardar archivo modificado
    # =========================================================================
    if content != original_content:
        with open('gemini_agent_bot.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'\n=== Patches aplicados exitosamente ===')
        for p in patches_applied:
            print(f'  [OK] {p}')
        print(f'\nTotal patches aplicados: {len(patches_applied)}')
    else:
        print('WARN: No se realizaron cambios. Verifica que los strings de busqueda sean correctos.')
    
    return patches_applied


if __name__ == '__main__':
    apply_patches()

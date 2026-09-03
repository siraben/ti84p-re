/* Runtime and allocation support shared by direct-core TilEm probes. */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

#include <tilem.h>

#include "tilem_probe_support.h"

void tilem_free(void *ptr) { free(ptr); }
void *tilem_malloc(size_t size) { return malloc(size); }
void *tilem_malloc0(size_t size) { return calloc(1, size); }
void *tilem_malloc_atomic(size_t size) { return malloc(size); }
void *tilem_try_malloc(size_t size) { return malloc(size); }
void *tilem_try_malloc0(size_t size) { return calloc(1, size); }
void *tilem_try_malloc_atomic(size_t size) { return malloc(size); }
void *tilem_realloc(void *ptr, size_t size) { return realloc(ptr, size); }

const char *tilem_gettext(const char *message) { return message; }

static void log_message(const char *kind, const char *message, va_list args) {
    fprintf(stderr, "TilEm %s: ", kind);
    vfprintf(stderr, message, args);
    fputc('\n', stderr);
}

void tilem_message(TilemCalc *calc, const char *message, ...) {
    va_list args;
    (void) calc;
    va_start(args, message);
    log_message("message", message, args);
    va_end(args);
}

void tilem_warning(TilemCalc *calc, const char *message, ...) {
    va_list args;
    (void) calc;
    va_start(args, message);
    log_message("warning", message, args);
    va_end(args);
}

void tilem_internal(TilemCalc *calc, const char *message, ...) {
    va_list args;
    (void) calc;
    va_start(args, message);
    log_message("internal error", message, args);
    va_end(args);
}

TilemCalc *tilem_probe_new_calc(void) {
    TilemCalc *calc = tilem_calc_new(TILEM_CALC_TI84P);
    if (calc == NULL) {
        fputs("cannot allocate TilEm TI-84 Plus core\n", stderr);
        exit(1);
    }
    return calc;
}

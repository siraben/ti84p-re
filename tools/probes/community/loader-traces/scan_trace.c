/* Scan large TLMT v2 traces without retaining records in memory. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint16_t le16(const unsigned char *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void short_read(const char *what) {
    fprintf(stderr, "short TLMT %s\n", what);
    exit(2);
}

int main(int argc, char **argv) {
    unsigned char header[20], record[47], write[5], key[8];
    uint64_t instructions = 0, writes = 0;
    uint64_t pc_9d95 = 0, pc_9dab = 0, pc_9da1 = 0;
    uint64_t pc_9872 = 0, pc_9881 = 0, pc_077e = 0, pc_6745 = 0;
    uint64_t pc_9dd7 = 0, pc_9ddd = 0, pc_9de1 = 0, pc_9de7 = 0;
    uint64_t safe2_copy_writes = 0, safe2_overread_writes = 0;
    uint64_t source_one = 0, source_two = 0, marker_42 = 0;
    uint32_t source_address = 0;
    uint32_t pending_address = 0;
    unsigned char pending_value = 0;
    int pending = 0;
    int loadtse_active = 0;
    int stream_active = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: %s TRACE\n", argv[0]);
        return 2;
    }
    FILE *stream = fopen(argv[1], "rb");
    if (!stream) {
        perror(argv[1]);
        return 2;
    }
    if (fread(header, 1, sizeof header, stream) != sizeof header)
        short_read("header");
    if (memcmp(header, "TLMT", 4) != 0 || le16(header + 4) != 2) {
        fprintf(stderr, "expected a TLMT v2 trace\n");
        return 2;
    }
    if (fseek(stream, (long)le32(header + 16), SEEK_CUR) != 0) {
        perror("initial snapshot seek");
        return 2;
    }

    for (;;) {
        int type = fgetc(stream);
        if (type == EOF)
            break;
        if (type == 1) {
            if (fread(record, 1, sizeof record, stream) != sizeof record)
                short_read("instruction");
            uint16_t pc = le16(record);
            instructions++;
            pc_9d95 += pc == 0x9d95;
            if (pc == 0x9d95)
                loadtse_active = 1;
            pc_9dab += pc == 0x9dab;
            pc_9da1 += pc == 0x9da1;
            pc_9872 += pc == 0x9872;
            pc_9881 += pc == 0x9881;
            pc_077e += pc == 0x077e;
            pc_6745 += pc == 0x6745;
            pc_9dd7 += pc == 0x9dd7;
            pc_9ddd += pc == 0x9ddd;
            pc_9de1 += pc == 0x9de1;
            pc_9de7 += pc == 0x9de7;

            /* TLMT emits writes while an instruction runs and its instruction
               record afterwards.  Attribute pending writes to this PC. */
            if (pending) {
                if (pc == 0x9dac) {
                    source_address = pending_address;
                    source_one += pending_value == 1;
                    source_two += pending_value == 2;
                }
                if (pc == 0x9da1 && pending_address == 0x9da6)
                    marker_42 += pending_value == 0x42;
                if (pc == 0x9de7 && pending_address >= 0x8a3a &&
                    pending_address < 0x8a3a + 531) {
                    safe2_copy_writes++;
                    if (pending_address >= 0x8a3a + 388)
                        safe2_overread_writes++;
                }
                pending = 0;
            }
            if (pc == 0x9ddd)
                stream_active = 1;
            if (pc == 0x9de0)
                stream_active = 0;
            if (pc == 0x9872)
                loadtse_active = 0;
        } else if (type == 2) {
            if (fread(write, 1, sizeof write, stream) != sizeof write)
                short_read("memory-write");
            writes++;
            pending_address = le32(write);
            pending_value = write[4];
            pending = 1;
            if (loadtse_active && stream_active && pending_address >= 0x8a3a &&
                pending_address < 0x8a3a + 531) {
                safe2_copy_writes++;
                if (pending_address >= 0x8a3a + 388)
                    safe2_overread_writes++;
            }
        } else if (type == 3) {
            if (fread(key, 1, sizeof key, stream) != sizeof key)
                short_read("key-event");
        } else {
            fprintf(stderr, "unknown TLMT record type %d\n", type);
            return 2;
        }
    }
    fclose(stream);
    puts("instruction_records,memory_write_records,pc_9D95_hits,pc_9DAB_hits,"
         "pc_9DA1_hits,pc_9872_hits,pc_9881_hits,pc_077E_hits,"
         "pc_6745_hits,pc_9DD7_hits,pc_9DDD_hits,pc_9DE1_hits,"
         "pc_9DE7_hits,safe2_copy_writes,safe2_overread_writes,source_address,"
         "source_store_1,source_store_2,client_marker_42");
    printf("%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ","
           "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ","
           "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ","
           "%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ","
           "%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
           instructions, writes, pc_9d95, pc_9dab, pc_9da1, pc_9872,
           pc_9881, pc_077e, pc_6745, pc_9dd7, pc_9ddd, pc_9de1, pc_9de7,
           safe2_copy_writes, safe2_overread_writes, (uint64_t)source_address,
           source_one, source_two, marker_42);
    return 0;
}

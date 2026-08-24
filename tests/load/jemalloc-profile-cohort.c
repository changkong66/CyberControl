#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PROFILE_COHORT_BLOCKS 256

static void *profile_cohort[MAX_PROFILE_COHORT_BLOCKS];
static size_t profile_cohort_count;

__attribute__((noinline, visibility("default")))
size_t cybercontrol_profile_allocate(size_t block_size, size_t block_count) {
    size_t allocated = 0;

    if (block_size == 0 || block_count == 0 ||
        block_count > MAX_PROFILE_COHORT_BLOCKS - profile_cohort_count) {
        return 0;
    }
    for (size_t index = 0; index < block_count; index++) {
        void *block = malloc(block_size);
        if (block == NULL) {
            break;
        }
        memset(block, (int)(0x41U + (index % 23U)), block_size);
        profile_cohort[profile_cohort_count++] = block;
        allocated += block_size;
    }
    return allocated;
}

__attribute__((noinline, visibility("default")))
void cybercontrol_profile_release(void) {
    while (profile_cohort_count > 0) {
        free(profile_cohort[--profile_cohort_count]);
        profile_cohort[profile_cohort_count] = NULL;
    }
}

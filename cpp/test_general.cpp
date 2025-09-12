/**
 * @file test_general.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-12
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <atomic>
#include <thread>
#include <iostream>

std::atomic<int> count = {0};
int main() {

    std::atomic<int> threads[5] = {0,0,0,0,0};
    std::cout << std::boolalpha << threads[0].is_lock_free() << std::endl;

    std::thread t1([](){
        count.fetch_add(1);
    });
    std::thread t2([](){
        count++; // identical to fetch_add
        count += 1; // identical to fetch_add
    });

    t1.join();
    t2.join();

    std::cout << count << std::endl;
    return 0;
}
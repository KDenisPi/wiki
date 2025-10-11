/**
 * @file test_dict_class.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-24
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <string>
#include <iostream>

#include <fstream>
#include <memory>
#include <random>
#include <tuple>

#include "dict_class.h"

using dict_key = std::string;
using dict_val = std::tuple<std::string, std::string>;

int main (int argc, char* argv[])
{
    //const std::type_info& r1 = typeid(dict_2);
    //std::cout << " Is tuple: " << (std::string(typeid(dict_2).name()).find("tuple") != std::string::npos) << " Name: " << typeid(dict_2).name() << std::endl;
    //std::cout << " " << typeid(std::string).name() << std::endl;

    std::mt19937_64 rng(std::chrono::high_resolution_clock::now().time_since_epoch().count());
    std::uniform_int_distribution<unsigned int> dist(1, 10000000);


    std::shared_ptr<wiki::DictClass<dict_key, dict_val>> dict = std::make_shared<wiki::DictClass<dict_key, dict_val>>("P31");
    auto l_rec = dict->load();
    std::cout << "Loaded records: " << l_rec << std::endl;

    for(int i = 0; i < 100; i++){
        unsigned int randomNumber = dist(rng);
        const std::string item = "Q" + std::to_string(randomNumber);
        const auto val = std::make_tuple(std::string("item"), std::string("place of birth"));
        dict->put(item, val);
    }

    dict->save();
    dict.reset();


/*
    std::ifstream inputFile("P31.csv");
    if(inputFile.is_open()){
        std::string line;
        int i_line = 0;
        while(std::getline(inputFile, line)){
            const std::string item_id = line.substr(0, line.find(";"));
            std::cout << i_line << " " << item_id << std::endl;
            i_line++;
        }

    }
    inputFile.close();
*/

    exit(EXIT_SUCCESS);
}
/**
 * @file dict_class.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-11-14
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <iostream>
#include <vector>

#include "dict_class.h"

namespace wiki {

template<>
void DictClass<std::string,std::tuple<std::string, std::string>>::put_value(std::fstream& outputFile, const std::tuple<std::string, std::string>& value){
    for_each(value, [&](const auto& val) {
        outputFile << ";" << val;
    });
}

template<>
void DictClass<std::string,std::vector<std::string>>::put_value(std::fstream& outputFile, const std::vector<std::string>& value){
    for(auto val : value){
        outputFile << ";" << val;
    }
}

}
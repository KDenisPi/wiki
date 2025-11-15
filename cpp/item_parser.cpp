/**
 * @file item_parser.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-11-04
 *
 * @copyright Copyright (c) 2025
 *
 */
#include <iostream>

#include "item_parser.h"

namespace wiki {

template <>
const data_value ItemParser::pack<data_value>(const data_value& data){
    return data;
}

template <>
const std::string ItemParser::pack<std::string>(const data_value& data){
    return (data.size()>1 ? data[1] : std::string()); //::get<1>(data);
}

}
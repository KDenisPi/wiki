/**
 * @file prop_dict.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-12
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <fcntl.h>
#include <unistd.h>

#include "prop_dict.h"

namespace wiki {

/**
 * @brief
 *
 * @param filename
 * @return true
 * @return false
 */
bool Properties::load(const std::string& filename){
    int fd_prop = open(filename.c_str(), O_RDONLY);
    if(fd_prop == -1){
        std::cout << "Error opening file " << filename << " Error: " << errno << std::endl; // Print an error message
        return false;
    }

    size_t b_read = b_read = read(fd_prop, buffer, MAX_LINE_LENGTH-1);
    if(b_read == -1){
        std::cout << "Error reading file " << filename << " Error: " << errno << std::endl; // Print an error message
    }
    else{
        buffer[b_read] = 0x00;

        d_prop.Parse(buffer);
        if(d_prop.HasParseError()){
            auto err = d_prop.GetParseError();
            std::cout << filename << " Parse error: " << std::to_string(err) << " Offset: " << d_prop.GetErrorOffset() << std::endl;
        }
        else{
            loaded = true;
        }
    }

    close(fd_prop);
    return loaded;
}

/**
 * @brief
 *
 * @param prop_id
 * @return const p_info
 */
const pInfo Properties::get(const pID& prop_id) const{
    auto prop = d_prop.FindMember(prop_id.c_str());
    if(d_prop.MemberEnd() != prop){
        return pInfo(prop_id, std::string(prop->value[0].GetString()), std::string(prop->value[1].GetString()));
    }

    return pInfo(pID(), std::string(), std::string());
}

} //namespace
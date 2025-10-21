/**
 * @file item_reader.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief Read WiKi Item information from file and TODO
 * @version 0.1
 * @date 2025-08-13
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_READER_H_
#define WIKI_ITEM_READER_H_

#include <string>
#include <ostream>
#include <iostream>
#include <string.h>

#include "defines.h"

namespace wiki {

class ItemReader{
public:
    /**
     * @brief Construct a new Item Reader object
     *
     */
    ItemReader() {}

    /**
     * @brief Destroy the Item Reader object
     *
     */
    ~ItemReader() {
        close();
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    bool init(const std::string filename){
        items_file = filename;
        fp_prop = fopen(filename.c_str(), "rb");
        // Check if the file was opened successfully
        if (fp_prop == NULL) {
            std::cerr << "Error reading file " << filename << " Error: " << errno << std::endl; // Print an error message
            return false;
        }

        if( pos > 0 ){
            auto res = std::fseek(fp_prop, pos, SEEK_SET);
            if( res < 0 ){
                std::cerr << "Error set position for " << filename << " Error: " << errno << std::endl; // Print an error message
                return false;
            }
        }

        return true;
    }

    /**
     * @brief Get the next Item line from the file
     *
     * @param buff
     * @param buff_size
     * @return true
     * @return false
     */
    bool next(char* buff, size_t buff_size){
        if(fgets(buff, buff_size, fp_prop) != NULL) {
            const auto len = strlen(buff);
            //std::cout << "Length: " << len << " Char: " << buff[len-2] << std::endl;
            if(buff[len-1] == '\n' && buff[len-2] == ','){
                buff[len-2] = 0;
            }
            pos = ftell(fp_prop);
            return true;
        }
        return false;
    }

    /**
     * @brief
     *
     */
    void close(){
        if(fp_prop != nullptr){
            fclose(fp_prop);
            fp_prop = nullptr;
        }
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    const bool is_ready() const{
        return (fp_prop != nullptr);
    }

    /**
     * @brief Get the pos object
     *
     * @return const long
     */
    const long get_pos() const {
        return pos;
    }

    void set_pos( const long start_pos ){
        pos = start_pos;
    }

    const auto get_filename() const {
        return items_file;
    }

private:
    std::string items_file;
    FILE *fp_prop = nullptr;
    long pos = 0;
    bool loaded = false;
};

} //namespace
#endif